"""Scores jobs against your profile with AI, resilient to busy or failing models.

How it copes with problems:
  - Jobs are scored in small batches, so a day needs ~8 calls instead of ~40.
  - Several backends are tried in order (config: scoring.backends). If one is
    overloaded (503) or rate-limited (429), the next is tried right away.
  - If every backend is busy, it waits (30s, 60s, 120s...) and tries again,
    within the time budget scoring.max_minutes.
  - A retired model (404) is swapped for the newest available one automatically.
  - A bad key (400/401/403) or a used-up daily quota drops that backend only.
  - Jobs that still couldn't be scored are returned as unscored; the pipeline
    shows them with a keyword score and re-scores them on the next run.
"""
import json
import logging
import os
import re
import time

log = logging.getLogger(__name__)

PROMPT = """You are a strict, realistic technical recruiter for the Indian tech market.
Assess how well EACH job below fits the candidate. Be honest: do not inflate scores.

CANDIDATE PROFILE
{profile}

CANDIDATE PREFERENCES
{preferences}

JOBS
{jobs}

Return ONLY a JSON object of the form {{"results": [ ... ]}} with one entry per job, each with
exactly these keys:
  "job": the job's id exactly as given (e.g. "J1"),
  "fit_score": integer 0-100 (85+ = near-perfect match of skills, level and role; 65-84 = good; below 65 = weak),
  "role_type": one of {role_types}, or "other" (which of the candidate's target roles this job is),
  "summary": one sentence on why this fits or does not,
  "matched_skills": up to 6 skills from the JD the candidate clearly has,
  "gaps": up to 4 JD requirements the candidate lacks or has only lightly,
  "experience_ok": true if the role suits about 2 years of experience,
  "remote_open_to_india": true / false / null (null if not a remote role or unclear),
  "salary_estimate_lpa": {{"min": number, "max": number}} or null. Only estimate when no salary
     is listed; base it on company type, role, city and level in India; be conservative.
     Use null if you cannot estimate,
  "application_note": 3-4 sentences the candidate can send to the recruiter. Use only facts
     from the profile, link them to this JD, no exaggeration, no greeting or sign-off."""

JOB_BLOCK = """--- {jid} ---
Title: {title}
Company: {company}
Location: {location} (remote: {remote})
Listed salary: {salary}
Listed experience: {experience}
Description:
{description}
"""

OPENAI_COMPATIBLE = {
    "openai": ("OPENAI_API_KEY", None),
    "groq": ("GROQ_API_KEY", "https://api.groq.com/openai/v1"),
    "openrouter": ("OPENROUTER_API_KEY", "https://openrouter.ai/api/v1"),
}
BUSY_WAITS = [30, 60, 120, 180]


def _extract_json(text: str):
    text = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M).strip()
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    start = min(starts)
    end = max(text.rfind("}"), text.rfind("]"))
    return json.loads(text[start:end + 1])


def _status(exc):
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    try:
        return int(code)
    except (TypeError, ValueError):
        m = re.match(r"\s*(\d{3})\b", str(exc))
        return int(m.group(1)) if m else None


def _version(name: str):
    nums = re.findall(r"\d+(?:\.\d+)?", name.split("/")[-1])
    return tuple(float(n) for n in nums[:2]) or (0,)


class Backend:
    def __init__(self, provider: str, model: str):
        self.provider, self.model = provider, model
        self.swapped = False
        if provider == "gemini":
            from google import genai
            self.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        else:
            from openai import OpenAI
            key_env, base_url = OPENAI_COMPATIBLE[provider]
            self.client = OpenAI(api_key=os.environ[key_env], base_url=base_url)

    @property
    def name(self):
        return f"{self.provider}:{self.model}"

    def call(self, prompt: str):
        if self.provider == "gemini":
            from google.genai import types
            resp = self.client.models.generate_content(
                model=self.model, contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json",
                                                   temperature=0.2))
            return _extract_json(resp.text)
        resp = self.client.chat.completions.create(
            model=self.model, temperature=0.2,
            messages=[{"role": "system", "content": "Reply with valid JSON only."},
                      {"role": "user", "content": prompt}])
        return _extract_json(resp.choices[0].message.content)

    def find_replacement(self):
        """Gemini only: newest available Flash model of the same kind (Lite or not)."""
        if self.provider != "gemini":
            return None
        want_lite = "lite" in self.model
        try:
            names = []
            for m in self.client.models.list():
                actions = [a.lower() for a in (getattr(m, "supported_actions", None) or [])]
                name = (m.name or "").split("/")[-1]
                if "generatecontent" not in actions or "flash" not in name:
                    continue
                if any(w in name for w in ("image", "tts", "audio", "live", "embedding", "exp")):
                    continue
                if ("lite" in name) != want_lite:
                    continue
                names.append(name)
            names.sort(key=lambda n: ("preview" not in n, _version(n)), reverse=True)
            return names[0] if names else None
        except Exception as exc:
            log.warning("Could not list Gemini models: %s", exc)
            return None


class Scorer:
    def __init__(self, cfg: dict, profile: str, disabled: bool = False):
        self.cfg = cfg
        self.profile = profile
        sc = cfg["scoring"]
        self.delay = sc.get("delay_seconds", 4)
        self.batch_size = max(1, int(sc.get("batch_size", 5)))
        self.budget_end = time.monotonic() + 60 * sc.get("max_minutes", 20)
        self.errors, self.notes = [], []
        self.used = set()
        logging.getLogger("google_genai").setLevel(logging.WARNING)
        logging.getLogger("httpx").setLevel(logging.WARNING)
        self.backends = [] if disabled else self._build_backends(sc)

    def _build_backends(self, sc):
        specs = sc.get("backends") or [{"provider": "gemini", "model": sc.get("gemini_model", "")}]
        backends, missing = [], []
        for spec in specs:
            provider, model = spec.get("provider", "gemini"), spec.get("model", "")
            key_env = "GEMINI_API_KEY" if provider == "gemini" else OPENAI_COMPATIBLE.get(provider, ("?",))[0]
            if not os.getenv(key_env):
                missing.append(key_env)
                continue
            try:
                backends.append(Backend(provider, model))
            except Exception as exc:
                self.errors.append(f"Could not set up {provider}:{model}: {exc}")
        if not backends:
            self.errors.append("AI scoring off: no API key secret is set "
                               f"({', '.join(sorted(set(missing))) or 'none configured'}), so scores are keyword-based.")
        return backends

    @property
    def uses_ai(self):
        return bool(self.backends)

    def _drop(self, backend, reason):
        if backend in self.backends:
            self.backends.remove(backend)
        msg = f"{backend.name} {reason}"
        self.errors.append(msg)
        log.error(msg)

    def _prompt(self, batch):
        blocks = [JOB_BLOCK.format(
            jid=f"J{i + 1}", title=j.title, company=j.company, location=j.location or "not listed",
            remote=j.remote, salary=j.salary_text or "not listed",
            experience=j.experience_text or "not listed", description=j.description[:3500])
            for i, j in enumerate(batch)]
        roles = self.cfg["search"]["roles"]
        role_types = ", ".join(f'"{k}" ({v["label"]})' for k, v in roles.items())
        prefs = self.cfg.get("preferences") or f"- Minimum acceptable package {self.cfg['search']['salary']['min_lpa']} LPA"
        return PROMPT.format(profile=self.profile, preferences=prefs.strip(), role_types=role_types,
                             jobs="\n".join(blocks))

    @staticmethod
    def _map(data, batch):
        items = data.get("results", []) if isinstance(data, dict) else data
        out = {}
        for k, item in enumerate(items if isinstance(items, list) else []):
            if not isinstance(item, dict) or "fit_score" not in item:
                continue
            m = re.search(r"\d+", str(item.get("job", "")))
            idx = int(m.group()) - 1 if m else k
            if 0 <= idx < len(batch):
                out[batch[idx].id] = item
        return out

    def _try(self, backend, prompt, batch):
        """One call. Returns results, or None if this backend failed this time."""
        try:
            return self._map(backend.call(prompt), batch)
        except Exception as exc:
            code, msg = _status(exc), str(exc)
            short = msg[:180]
            if code == 404 and not backend.swapped:
                backend.swapped = True
                newer = backend.find_replacement()
                if newer and newer != backend.model:
                    self.notes.append(f"'{backend.model}' is no longer available, so '{newer}' was used. "
                                      "Update scoring.backends in config.yaml.")
                    log.warning("Model %s retired; switching to %s", backend.model, newer)
                    backend.model = newer
                    return self._try(backend, prompt, batch)
            if code in (400, 401, 403, 404):
                self._drop(backend, f"was turned off for this run ({short}). Check its API key and model name.")
            elif code == 429 and re.search(r"per ?day|daily|perday", msg, re.I):
                self._drop(backend, "has used up its free daily quota; it resets tomorrow.")
            else:
                log.warning("%s busy or failed (%s); trying the next option", backend.name, short)
            return None

    def _score_batch(self, batch):
        prompt = self._prompt(batch)
        busy_round = 0
        while self.backends and time.monotonic() < self.budget_end:
            for backend in list(self.backends):
                result = self._try(backend, prompt, batch)
                if result is not None:
                    self.used.add(backend.name)
                    time.sleep(self.delay)
                    return result
            if not self.backends:
                break
            wait = BUSY_WAITS[min(busy_round, len(BUSY_WAITS) - 1)]
            if time.monotonic() + wait > self.budget_end:
                break
            log.warning("All AI options are busy; waiting %ss before trying again", wait)
            time.sleep(wait)
            busy_round += 1
        return {}

    def score_many(self, jobs):
        """Returns {job_id: fit dict} for the jobs AI managed to score."""
        results = {}
        for i in range(0, len(jobs), self.batch_size):
            if not self.backends or time.monotonic() >= self.budget_end:
                break
            results.update(self._score_batch(jobs[i:i + self.batch_size]))
        missed = len(jobs) - len(results)
        if missed:
            self.notes.append(f"{missed} job{'s' if missed != 1 else ''} couldn't be checked by AI today "
                              "(it was busy); they show keyword scores and will be re-checked on the next run.")
        if self.used:
            log.info("AI scoring used: %s", ", ".join(sorted(self.used)))
        return results

    def heuristic(self, job) -> dict:
        kws = self.cfg["profile_keywords"]
        text = f"{job.title} {job.description}".lower()
        matched = [k for k in kws if re.search(r"(?<![a-z])" + re.escape(k) + r"(?![a-z])", text)]
        return {
            "fit_score": min(92, 45 + 5 * len(matched)),
            "role_type": job.role_bucket,
            "summary": f"Keyword match on {len(matched)} of your skills. Not checked by AI yet.",
            "matched_skills": matched[:6],
            "gaps": [],
            "experience_ok": True,
            "remote_open_to_india": None,
            "salary_estimate_lpa": None,
            "application_note": "",
            "heuristic": True,
        }
