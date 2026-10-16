import hashlib
import html
import re
from dataclasses import asdict, dataclass, field
from typing import Optional

_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


def clean_text(value) -> str:
    """Turn HTML-ish or nested values into plain text."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(clean_text(v) for v in value if v)
    if isinstance(value, dict):
        for key in ("name", "text", "label", "value", "title"):
            if value.get(key):
                return clean_text(value[key])
        return ""
    text = html.unescape(str(value))
    text = re.sub(r"<(br|/p|/li|/div|/h\d)[^>]*>", "\n", text, flags=re.I)
    text = _TAG.sub(" ", text)
    lines = [_SPACE.sub(" ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


@dataclass
class Job:
    title: str
    company: str
    location: str
    url: str
    description: str = ""
    salary_text: str = ""
    experience_text: str = ""
    posted: str = ""
    source: str = ""
    remote: bool = False
    workplace: str = ""

    # Filled in by the pipeline
    id: str = ""
    role_bucket: str = ""
    salary_min_lpa: Optional[float] = None
    salary_max_lpa: Optional[float] = None
    salary_estimated: bool = False
    exp_min: Optional[float] = None
    exp_max: Optional[float] = None
    prescore: float = 0.0
    fit: dict = field(default_factory=dict)
    trend: dict = field(default_factory=dict)
    first_seen: str = ""

    def __post_init__(self):
        self.title = clean_text(self.title)
        self.company = clean_text(self.company) or "Unknown company"
        self.location = clean_text(self.location)
        self.description = clean_text(self.description)
        self.salary_text = clean_text(self.salary_text)
        self.experience_text = clean_text(self.experience_text)
        if not self.id:
            city = _norm(self.location.split(",")[0])
            key = f"{_norm(self.company)}|{_norm(self.title)}|{city}"
            self.id = hashlib.sha1(key.encode()).hexdigest()[:16]

    def to_page_dict(self) -> dict:
        d = asdict(self)
        d["description"] = self.description[:600]  # the page only needs a preview
        return d
