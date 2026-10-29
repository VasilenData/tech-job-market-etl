"""One full extract -> transform -> load cycle, then export report CSVs for the repo.

    python -m pipeline.run                                  # embedded local Postgres
    DATABASE_URL=postgresql://... python -m pipeline.run    # your own Postgres (CI uses a service container)
"""
import csv
import logging
import os
import sys
import tempfile

import psycopg2

from pipeline import extract, load, transform

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
log = logging.getLogger("pipeline")


def connect():
    url = os.environ.get("DATABASE_URL")
    if url:
        return psycopg2.connect(url)
    import pgserver  # embedded Postgres for zero-setup local runs
    return psycopg2.connect(pgserver.get_server(tempfile.mkdtemp()).get_uri())


def export_reports(conn, out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    blocks = open(os.path.join(ROOT, "sql", "reports.sql")).read().split("-- name: ")[1:]
    for block in blocks:
        name, sql = block.split("\n", 1)
        with conn.cursor() as cur:
            cur.execute(sql); cols = [c[0] for c in cur.description]; rows = cur.fetchall()
        with open(os.path.join(out_dir, f"{name.strip()}.csv"), "w", newline="") as fh:
            w = csv.writer(fh); w.writerow(cols); w.writerows(rows)
        log.info("report %s: %d rows", name.strip(), len(rows))


def append_history(conn, path: str) -> None:
    """Keep a durable daily time series in the repo (CI databases are ephemeral). One row per day and role family."""
    from datetime import date
    today = date.today().isoformat()
    existing = []
    if os.path.exists(path):
        with open(path, newline="") as fh:
            existing = [r for r in csv.reader(fh)][1:]
    existing = [r for r in existing if r[0] != today]  # re-running the same day replaces that day
    with conn.cursor() as cur:
        cur.execute("SELECT role_family, COUNT(*), SUM(is_remote::int) FROM jobs WHERE last_seen_on = (SELECT MAX(last_seen_on) FROM jobs) GROUP BY 1 ORDER BY 1")
        new = [[today, fam, n, rem] for fam, n, rem in cur.fetchall()]
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["day", "role_family", "active_jobs", "remote_jobs"]); w.writerows(existing + new)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    conn = connect()
    with conn.cursor() as cur:
        cur.execute(open(os.path.join(ROOT, "sql", "schema.sql")).read())
    conn.commit()
    sources = [("arbeitnow", extract.fetch_arbeitnow, transform.normalize_arbeitnow),
               ("remotive", extract.fetch_remotive, transform.normalize_remotive)]
    failures = 0
    for name, fetch, norm in sources:
        try:
            raw = fetch()
            jobs, rejects = transform.clean([norm(r) for r in raw])
            for jid, why in rejects[:20]:
                log.warning("rejected %s: %s", jid, why)
            stats = load.load(conn, jobs, name, len(raw), len(rejects))
            log.info("%s: %s", name, stats)
        except Exception:
            failures += 1
            log.exception("source %s failed", name)
            conn.rollback()
    if failures == len(sources):
        return 1  # nothing loaded, fail the run
    export_reports(conn, os.path.join(ROOT, "data", "reports"))
    append_history(conn, os.path.join(ROOT, "data", "history.csv"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
