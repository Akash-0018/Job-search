"""Hard filters that run before any AI call. Each returns a skip reason or None."""
import datetime as dt
import re

FOREIGN_ONLY = ("united states", "usa", "u.s.", "us only", "us-only", "canada", "united kingdom",
                "uk only", "europe", "emea", "germany", "france", "netherlands", "latam",
                "north america", "americas", "australia", "brazil", "mexico", "japan")
INDIA_OK = ("india", "apac", "asia", "anywhere", "worldwide", "global")
LAKH_WORDS = re.compile(r"lpa|lakh|lac|\d\s*l\b|\bl\b", re.I)
NUM = re.compile(r"(\d+(?:\.\d+)?)\s*(k|lpa|lakhs?|lacs?|l)?(?![a-z])", re.I)


def _has_word(text: str, word: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])", text) is not None


# ---------- salary ----------
def parse_salary_lpa(text: str, usd_to_inr: float = 84.0):
    """'8-14 Lacs P.A.' -> (8, 14); '₹6,00,000 - ₹9,00,000' -> (6, 9); '$40K-$60K' -> USD converted.
    Returns (None, None) when nothing reliable can be read."""
    if not text:
        return None, None
    t = text.lower().replace(",", "")
    if "not disclosed" in t or "hour" in t or "/hr" in t:
        return None, None
    usd = "$" in t or "usd" in t
    monthly = any(w in t for w in ("month", "/mo", "per mo", " pm", "p.m"))
    lakh_context = bool(LAKH_WORDS.search(t)) and not usd
    values = []
    for num, unit in NUM.findall(t):
        v = float(num)
        unit = (unit or "").lower()
        if unit in ("lpa", "lakh", "lakhs", "lac", "lacs", "l") or (lakh_context and v < 200 and not unit):
            values.append(v)  # already lakhs
            continue
        if unit == "k":
            v *= 1000
        if v < 1000:
            continue  # stray small number (years, counts) - ignore
        if usd:
            v *= usd_to_inr
        if monthly:
            v *= 12
        values.append(v / 100000)
    if not values:
        return None, None
    lo, hi = min(values), max(values)
    if monthly and lakh_context:
        lo, hi = lo * 12, hi * 12
    if hi > 500:  # nonsense
        return None, None
    return round(lo, 1), round(hi, 1)


# ---------- experience ----------
EXP_RANGE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:-|to|–|—)\s*(\d+(?:\.\d+)?)\s*\+?\s*(?:yrs?|years?)", re.I)
EXP_MIN = re.compile(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:yrs?|years?)(?:\s+of)?(?:\s+\w+){0,3}\s+experience", re.I)
EXP_SIMPLE = re.compile(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:yrs?|years?)", re.I)


def parse_experience(exp_text: str, description: str):
    for text, patterns in ((exp_text, (EXP_RANGE, EXP_SIMPLE)), (description, (EXP_RANGE, EXP_MIN))):
        if not text:
            continue
        for pat in patterns:
            m = pat.search(text)
            if m:
                lo = float(m.group(1))
                hi = float(m.group(2)) if m.lastindex and m.lastindex >= 2 else None
                if lo <= 20:
                    return lo, hi
    return None, None


# ---------- dates ----------
def parse_date(value: str):
    if not value:
        return None
    v = str(value).strip()
    if v.isdigit() and len(v) >= 12:  # epoch ms
        return dt.datetime.fromtimestamp(int(v) / 1000, dt.timezone.utc).date()
    try:
        return dt.datetime.fromisoformat(v.replace("Z", "+00:00")[:25]).date()
    except ValueError:
        pass
    m = re.search(r"(\d+)\s*(hour|day|week|month)s?\s*ago", v.lower())
    if m:
        n, unit = int(m.group(1)), m.group(2)
        days = {"hour": 0, "day": n, "week": 7 * n, "month": 30 * n}[unit]
        return dt.date.today() - dt.timedelta(days=days)
    if "just now" in v.lower() or "today" in v.lower():
        return dt.date.today()
    return None


# ---------- main filter ----------
def role_bucket(job, roles: dict):
    title = job.title.lower()
    desc = job.description.lower()
    for key, role in roles.items():
        if any(_has_word(title, kw) for kw in role["title_keywords"]):
            if not desc or any(_has_word(desc, w) for w in role.get("jd_must_mention", [])):
                return key
    return None


def check(job, cfg: dict, today: dt.date, lookback_days: int):
    """Annotates the job and returns a skip reason, or None if it passes."""
    s = cfg["search"]
    title = job.title.lower()

    if any(_has_word(title, w) for w in s["title_exclude"]):
        return "title excluded (seniority or stack)"

    bucket = role_bucket(job, s["roles"])
    if not bucket:
        return "not a target role"
    job.role_bucket = bucket

    loc = job.location.lower()
    in_city = any(c in loc for c in s["locations"])
    is_remote = job.remote or "remote" in loc
    if is_remote and not in_city:
        if not s.get("include_remote", True):
            return "remote not wanted"
        if "hybrid" in (job.workplace or "").lower() and s.get("exclude_hybrid_remote", True):
            return "hybrid outside target cities"
        if any(w in loc for w in FOREIGN_ONLY) and not any(w in loc for w in INDIA_OK):
            return "remote but not open to India"
        job.remote = True
    elif not in_city:
        return "outside Bangalore/Chennai"

    posted = parse_date(job.posted)
    if posted and (today - posted).days > lookback_days:
        return "posting too old"

    job.exp_min, job.exp_max = parse_experience(job.experience_text, job.description)
    if job.exp_min is not None and job.exp_min > s["experience"]["max_min_years"]:
        return "needs more experience"

    sal = s["salary"]
    job.salary_min_lpa, job.salary_max_lpa = parse_salary_lpa(job.salary_text, sal.get("usd_to_inr", 84))
    if job.salary_min_lpa is not None and job.salary_min_lpa < sal["min_lpa"]:
        return f"salary below {sal['min_lpa']} LPA"
    if job.salary_min_lpa is None and sal["undisclosed"] == "exclude":
        return "salary not listed"
    return None


def prescore(job, keywords) -> float:
    text = f"{job.title} {job.description}".lower()
    hits = sum(1 for kw in keywords if _has_word(text, kw))
    bonus = 3 if job.role_bucket == "ai_engineer" else 1
    bonus += 1 if job.salary_min_lpa else 0
    return hits + bonus
