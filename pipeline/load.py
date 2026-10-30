"""Idempotent load into PostgreSQL: re-running never duplicates rows, it updates last_seen_on."""
from datetime import date


UPSERT_JOB = """
INSERT INTO jobs (job_id, source, title, company_id, location, is_remote, job_type, role_family, url, posted_at, first_seen_on, last_seen_on)
VALUES (%(job_id)s, %(source)s, %(title)s, %(company_id)s, %(location)s, %(is_remote)s, %(job_type)s, %(role_family)s, %(url)s, %(posted_at)s, %(today)s, %(today)s)
ON CONFLICT (job_id) DO UPDATE SET
    title = EXCLUDED.title, location = EXCLUDED.location, is_remote = EXCLUDED.is_remote, job_type = EXCLUDED.job_type,
    role_family = EXCLUDED.role_family, url = EXCLUDED.url, last_seen_on = EXCLUDED.last_seen_on
RETURNING (xmax = 0) AS inserted;
"""


def load(conn, jobs: list[dict], source: str, fetched: int, rejected: int, today: date | None = None) -> dict:
    today = today or date.today()
    inserted = updated = 0
    with conn.cursor() as cur:
        for j in jobs:
            cur.execute("INSERT INTO companies (name) VALUES (%s) ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING company_id", (j["company"],))
            company_id = cur.fetchone()[0]
            cur.execute(UPSERT_JOB, {**j, "company_id": company_id, "today": today})
            if cur.fetchone()[0]: inserted += 1
            else: updated += 1
            for skill in j["skills"]:
                cur.execute("INSERT INTO skills (name) VALUES (%s) ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING skill_id", (skill,))
                cur.execute("INSERT INTO job_skills (job_id, skill_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (j["job_id"], cur.fetchone()[0]))
        stats = {"fetched": fetched, "valid": len(jobs), "rejected": rejected, "inserted": inserted, "updated": updated}
        cur.execute("INSERT INTO pipeline_runs (run_date, source, fetched, valid, rejected, inserted, updated) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (today, source, fetched, len(jobs), rejected, inserted, updated))
    conn.commit()
    return stats
