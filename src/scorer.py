"""Scores each job against your profile with an LLM (Gemini or OpenAI).

Falls back to a keyword heuristic when no API key is set, so the page still builds.
"""
import json
import logging
import os
import re
import time

log = logging.getLogger(__name__)

PROMPT = """You are a strict, realistic technical recruiter for the Indian tech market.
Assess how well this job fits the candidate. Be honest: do not inflate scores.

CANDIDATE PROFILE
{profile}

CANDIDATE PREFERENCES
- Target roles: AI Engineer, Python Backend Developer, Forward Deployed Engineer
- Locations: Bangalore, Chennai, or 100% remote open to India-based candidates
- About 2 years of experience; minimum acceptable package {min_lpa} LPA

JOB
Title: {title}
Company: {company}
Location: {location} (remote: {remote})
Listed salary: {salary}
Listed experience: {experience}
Description:
{description}

Return ONLY a JSON object with exactly these keys:
{{
  "fit_score": integer 0-100 (85+ = near-perfect match of skills, level and role; 65-84 = good; below 65 = weak),
  "role_type": one of "ai_engineer", "python_backend", "fde", "other",
  "summary": one sentence on why this fits or does not,
  "matched_skills": up to 6 skills from the JD the candidate clearly has,
  "gaps": up to 4 JD requirements the candidate lacks or has only lightly,
  "experience_ok": true if the role suits about 2 years of experience,
  "remote_open_to_india": true / false / null (null if not a remote role or unclear),
  "salary_estimate_lpa": {{"min": number, "max": number}} or null. Only estimate when no salary
     is listed; base it on company type, role, city and level in India; be conservative.
     Use null if you cannot estimate,
  "application_note": 3-4 sentences the candidate can send to the recruiter. Use only facts
     from the profile, link them to this JD, no exaggeration, no greeting or sign-off.
}}"""


def _extract_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


FATAL_CODES = {400, 401, 403, 404}   # wrong key, no access, retired model: retrying won't help


def _status(exc):
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    try:
        return int(code)
    except (TypeError, ValueError):
        return None


def _version(name: str):
    nums = re.findall(r"\d+(?:\.\d+)?", name.split("/")[-1])
    return tuple(float(n) for n in nums[:2]) or (0,)


class Scorer:
    def __init__(self, cfg: dict, profile: str, disabled: bool = False):
        self.cfg = cfg
        self.profile = profile
        sc = cfg["scoring"]
        self.provider = "none" if disabled else sc.get("provider", "gemini")
        self.delay = sc.get("delay_seconds", 6)
        self.budget_end = time.monotonic() + 60 * sc.get("max_minutes", 15)
        self.client = None
        self.errors = []
        self.failures_in_a_row = 0
        self.tried_model_switch = False
        logging.getLogger("google_genai").setLevel(logging.WARNING)
        logging.getLogger("httpx").setLevel(logging.WARNING)
        if self.provider == "gemini" and os.getenv("GEMINI_API_KEY"):
            from google import genai
            self.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
            self.model = sc["gemini_model"]
        elif self.provider == "openai" and os.getenv("OPENAI_API_KEY"):
            from openai import OpenAI
            self.client = OpenAI()
            self.model = sc["openai_model"]
        elif self.provider != "none":
            self.errors.append(f"AI scoring off: {self.provider.upper()} API key secret is not set, "
                               "so scores are keyword-based estimates.")
            self.provider = "none"

    @property
    def uses_ai(self):
        return self.client is not None

    def _call(self, prompt: str) -> dict:
        if self.provider == "gemini":
            from google.genai import types
            resp = self.client.models.generate_content(
                model=self.model, contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json",
                                                   temperature=0.2))
            return _extract_json(resp.text)
        resp = self.client.chat.completions.create(
            model=self.model, temperature=0.2, response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}])
        return _extract_json(resp.choices[0].message.content)

    def _pick_newer_gemini(self):
        """The configured model was retired: find the newest Flash model this key can use."""
        try:
            names = []
            for m in self.client.models.list():
                actions = [a.lower() for a in (getattr(m, "supported_actions", None) or [])]
                name = (m.name or "").split("/")[-1]
                if "generatecontent" not in actions or "flash" not in name:
                    continue
                if any(w in name for w in ("image", "tts", "audio", "live", "embedding", "exp")):
                    continue
                names.append(name)
            if not names:
                return None
            # stable before preview, full Flash before Flash-Lite, then newest version
            names.sort(key=lambda n: ("preview" not in n, "lite" not in n, _version(n)), reverse=True)
            return names[0]
        except Exception as exc:
            log.warning("Could not list Gemini models: %s", exc)
            return None

    def _disable(self, reason: str):
        self.errors.append(reason)
        log.error(reason)
        self.client = None

    def score(self, job) -> dict:
        if self.uses_ai and time.monotonic() > self.budget_end:
            self._disable("AI scoring stopped after its time budget (scoring.max_minutes); "
                          "remaining jobs used keyword scores.")
        if not self.uses_ai:
            return self._heuristic(job)
        prompt = PROMPT.format(
            profile=self.profile, min_lpa=self.cfg["search"]["salary"]["min_lpa"],
            title=job.title, company=job.company, location=job.location or "not listed",
            remote=job.remote, salary=job.salary_text or "not listed",
            experience=job.experience_text or "not listed", description=job.description[:6000])
        for attempt in range(3):
            try:
                result = self._call(prompt)
                self.failures_in_a_row = 0
                time.sleep(self.delay)
                return result
            except Exception as exc:
                code = _status(exc)
                short = str(exc)[:200]
                if code == 404 and self.provider == "gemini" and not self.tried_model_switch:
                    self.tried_model_switch = True
                    newer = self._pick_newer_gemini()
                    if newer and newer != self.model:
                        self.errors.append(f"Gemini model '{self.model}' is no longer available, so today's "
                                           f"run used '{newer}'. Set scoring.gemini_model to it in config.yaml.")
                        log.warning("Switching Gemini model %s -> %s", self.model, newer)
                        self.model = newer
                        continue
                if code in FATAL_CODES:
                    self._disable(f"AI scoring turned off for this run: {self.provider} returned {code} "
                                  f"({short}). Check the API key secret and the model name in config.yaml.")
                    return self._heuristic(job)
                if attempt < 2:
                    wait = min(60, self.delay * (attempt + 2) * 2)
                    log.warning("Scoring '%s' failed (%s); retrying in %ss", job.title, short, wait)
                    time.sleep(wait)
        self.failures_in_a_row += 1
        if self.failures_in_a_row >= 3:
            self._disable("AI scoring turned off for this run after 3 jobs in a row failed; "
                          "remaining jobs used keyword scores.")
        else:
            self.errors.append(f"Could not score '{job.title}' at {job.company}; used keyword estimate.")
        return self._heuristic(job)

    def _heuristic(self, job) -> dict:
        kws = self.cfg["profile_keywords"]
        text = f"{job.title} {job.description}".lower()
        matched = [k for k in kws if re.search(r"(?<![a-z])" + re.escape(k) + r"(?![a-z])", text)]
        return {
            "fit_score": min(92, 45 + 5 * len(matched)),
            "role_type": job.role_bucket,
            "summary": f"Keyword match on {len(matched)} of your skills (AI scoring was off).",
            "matched_skills": matched[:6],
            "gaps": [],
            "experience_ok": True,
            "remote_open_to_india": None,
            "salary_estimate_lpa": None,
            "application_note": "",
            "heuristic": True,
        }
