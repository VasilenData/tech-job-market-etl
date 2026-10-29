"""Extract from public job APIs with retries. Both APIs are free and need no key."""
import time

import requests

ARBEITNOW = "https://www.arbeitnow.com/api/job-board-api"
REMOTIVE = "https://remotive.com/api/remote-jobs"
HEADERS = {"User-Agent": "tech-job-market-etl (portfolio project; github.com/VasilenData)"}


def get_json(url: str, params: dict | None = None, retries: int = 3):
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=30)
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)


def fetch_arbeitnow(pages: int = 3) -> list[dict]:
    out = []
    for p in range(1, pages + 1):
        data = get_json(ARBEITNOW, {"page": p}).get("data", [])
        if not data:
            break
        out += data
    return out


def fetch_remotive(categories=("data", "software-dev", "devops")) -> list[dict]:
    out = []
    for c in categories:
        out += get_json(REMOTIVE, {"category": c}).get("jobs", [])
    return out
