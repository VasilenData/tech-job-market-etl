"""Pure transformation + validation functions (no I/O), so they are easy to unit test."""
import html
import re
from datetime import datetime, timezone

SKILLS = {  # canonical name -> regex
    "Python": r"\bpython\b", "SQL": r"\bsql\b", "dbt": r"\bdbt\b", "Airflow": r"\bairflow\b",
    "Spark": r"\b(py)?spark\b", "Kafka": r"\bkafka\b", "Snowflake": r"\bsnowflake\b",
    "BigQuery": r"\bbigquery\b", "Redshift": r"\bredshift\b", "Databricks": r"\bdatabricks\b",
    "AWS": r"\baws\b|amazon web services", "Azure": r"\bazure\b", "GCP": r"\bgcp\b|google cloud",
    "Docker": r"\bdocker\b", "Kubernetes": r"\b(kubernetes|k8s)\b", "Terraform": r"\bterraform\b",
    "PostgreSQL": r"\bpostgres(ql)?\b", "Tableau": r"\btableau\b", "Power BI": r"\bpower ?bi\b",
    "Pandas": r"\bpandas\b", "ETL": r"\betl\b|\belt\b", "Scala": r"\bscala\b", "Java": r"\bjava\b(?!script)",
}
_FAMILY_RULES = [  # first match wins
    ("data_engineering", r"data engineer|analytics engineer|etl|data platform|data architect|big data|dataops|data infrastructure"),
    ("data_science_ml", r"data scien|machine learning|\bml\b|\bai\b|nlp|computer vision|research scientist"),
    ("data_analytics", r"data analy|business intelligence|\bbi\b|reporting analyst|analytics"),
    ("software", r"software|developer|backend|frontend|full.?stack|devops|sre|platform engineer"),
]


def strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(text or ""))).strip()


def classify_role(title: str) -> str:
    t = (title or "").lower()
    for family, pattern in _FAMILY_RULES:
        if re.search(pattern, t):
            return family
    return "other"


def extract_skills(*texts: str) -> list[str]:
    blob = " ".join(strip_html(t) for t in texts if t).lower()
    return sorted(name for name, pat in SKILLS.items() if re.search(pat, blob))


def _iso(ts) -> str | None:
    if ts is None or ts == "":
        return None
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).isoformat()


def normalize_arbeitnow(raw: dict) -> dict:
    return {
        "job_id": f"arbeitnow:{raw.get('slug')}", "source": "arbeitnow", "title": (raw.get("title") or "").strip(),
        "company": (raw.get("company_name") or "").strip(), "location": (raw.get("location") or "").strip() or None,
        "is_remote": bool(raw.get("remote")), "job_type": ", ".join(raw.get("job_types") or []) or None,
        "url": raw.get("url"), "posted_at": _iso(raw.get("created_at")),
        "skills": extract_skills(raw.get("title"), raw.get("description"), " ".join(raw.get("tags") or [])),
    }


def normalize_remotive(raw: dict) -> dict:
    return {
        "job_id": f"remotive:{raw.get('id')}", "source": "remotive", "title": (raw.get("title") or "").strip(),
        "company": (raw.get("company_name") or "").strip(), "location": (raw.get("candidate_required_location") or "").strip() or None,
        "is_remote": True, "job_type": raw.get("job_type"), "url": raw.get("url"), "posted_at": _iso(raw.get("publication_date")),
        "skills": extract_skills(raw.get("title"), raw.get("description"), " ".join(raw.get("tags") or [])),
    }


def validate(job: dict) -> tuple[bool, str]:
    """Reject records that would break the schema or pollute the data. Returns (ok, reason)."""
    if not job["job_id"].split(":", 1)[1] or job["job_id"].endswith(":None"):
        return False, "missing id"
    if not job["title"]:
        return False, "missing title"
    if not job["company"]:
        return False, "missing company"
    return True, ""


def clean(jobs: list[dict]) -> tuple[list[dict], list[tuple[str, str]]]:
    """Validate, add role_family, de-duplicate on job_id (keep the latest). Returns (valid_jobs, rejects)."""
    good, rejects, seen = [], [], {}
    for j in jobs:
        ok, why = validate(j)
        if not ok:
            rejects.append((j.get("job_id", "?"), why)); continue
        j = {**j, "role_family": classify_role(j["title"])}
        seen[j["job_id"]] = j
    good = list(seen.values())
    return good, rejects
