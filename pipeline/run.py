"""One full extract -> transform -> load cycle, then export report CSVs for the repo.

    python -m pipeline.run                                  # embedded local Postgres
    DATABASE_URL=postgresql://... python -m pipeline.run    # your own Postgres (CI uses a service container)
"""
import csv
import json
import logging
import os
import sys
import tempfile
from datetime import datetime, timezone

import psycopg2

from pipeline import extract, load, transform

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
log = logging.getLogger("pipeline")


def atomic_text(path, write):
    """Keep the last complete report/history if serialization or replacement fails."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", newline="", encoding="utf-8", dir=directory, delete=False) as stream:
            temporary = stream.name
            write(stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)


def connect():
    url = os.environ.get("DATABASE_URL")
    if url:
        return psycopg2.connect(url)
    import pgserver  # embedded Postgres for zero-setup local runs
    return psycopg2.connect(pgserver.get_server(tempfile.mkdtemp()).get_uri())


def export_reports(conn, out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(ROOT, "sql", "reports.sql"), encoding="utf-8") as stream:
        blocks = stream.read().split("-- name: ")[1:]
    for block in blocks:
        name, sql = block.split("\n", 1)
        with conn.cursor() as cur:
            cur.execute(sql); cols = [c[0] for c in cur.description]; rows = cur.fetchall()
        def write(fh):
            w = csv.writer(fh); w.writerow(cols); w.writerows(rows)
        atomic_text(os.path.join(out_dir, f"{name.strip()}.csv"), write)
        log.info("report %s: %d rows", name.strip(), len(rows))


def append_history(conn, path: str, today=None) -> None:
    """Keep a durable daily time series in the repo (CI databases are ephemeral). One row per day and role family."""
    today = (today or datetime.now(timezone.utc).date()).isoformat()
    existing = []
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as fh:
            existing = [r for r in csv.reader(fh)][1:]
    existing = [r for r in existing if r[0] != today]  # re-running the same day replaces that day
    with conn.cursor() as cur:
        cur.execute("SELECT role_family, COUNT(*), SUM(is_remote::int) FROM jobs WHERE in_latest_sample AND last_seen_on = %s GROUP BY 1 ORDER BY 1", (today,))
        new = [[today, fam, n, rem] for fam, n, rem in cur.fetchall()]
    def write(fh):
        w = csv.writer(fh); w.writerow(["day", "role_family", "active_jobs", "remote_jobs"]); w.writerows(existing + new)
    atomic_text(path, write)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    conn = None
    started = datetime.now(timezone.utc)
    status = {"started_at": started.isoformat(), "day": started.date().isoformat(),
              "publication": "withheld", "sources": {}}
    try:
        conn = connect()
        with conn.cursor() as cur:
            with open(os.path.join(ROOT, "sql", "schema.sql"), encoding="utf-8") as stream:
                cur.execute(stream.read())
        conn.commit()
        sources = [("arbeitnow", extract.fetch_arbeitnow, transform.normalize_arbeitnow),
                   ("remotive", extract.fetch_remotive, transform.normalize_remotive)]
        for name, fetch, norm in sources:
            try:
                raw = fetch()
                jobs, rejects = transform.normalize_batch(raw, norm)
                if not jobs:
                    raise ValueError("Source returned no valid postings")
                for jid, why in rejects[:20]:
                    log.warning("rejected %s: %s", jid, why)
                stats = load.load(conn, jobs, name, len(raw), len(rejects), today=started.date())
                status["sources"][name] = {"status": "loaded", **stats}
                log.info("%s: %s", name, stats)
            except Exception as error:
                status["sources"][name] = {"status": "failed", "error_type": type(error).__name__}
                log.exception("source %s failed", name)
                conn.rollback()
        if any(result["status"] != "loaded" for result in status["sources"].values()):
            log.error("Incomplete source coverage: reports and daily history remain unchanged")
            return 1
        export_reports(conn, os.path.join(ROOT, "data", "reports"))
        append_history(conn, os.path.join(ROOT, "data", "history.csv"), today=started.date())
        status["publication"] = "complete"
        return 0
    except Exception as error:
        status["error_type"] = type(error).__name__
        raise
    finally:
        status["finished_at"] = datetime.now(timezone.utc).isoformat()
        try:
            atomic_text(os.path.join(ROOT, "data", "run_status.json"),
                        lambda stream: json.dump(status, stream, indent=2))
        finally:
            if conn is not None:
                conn.close()


if __name__ == "__main__":
    sys.exit(main())
