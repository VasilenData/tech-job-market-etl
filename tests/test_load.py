"""Integration test against a real (embedded) PostgreSQL: loading twice must not duplicate rows."""
import os
import tempfile

import psycopg2
import pytest

pgserver = pytest.importorskip("pgserver")
from pipeline import load  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JOB = {"job_id": "t:1", "source": "t", "title": "Data Engineer", "company": "Acme", "location": "Berlin", "is_remote": True,
       "job_type": "full_time", "url": "http://x", "posted_at": "2026-01-01T00:00:00+00:00", "skills": ["Python", "SQL"], "role_family": "data_engineering"}


def test_load_is_idempotent():
    conn = psycopg2.connect(pgserver.get_server(tempfile.mkdtemp()).get_uri())
    with conn.cursor() as cur:
        cur.execute(open(os.path.join(ROOT, "sql", "schema.sql")).read())
    conn.commit()
    s1 = load.load(conn, [JOB], "t", 1, 0)
    s2 = load.load(conn, [dict(JOB, title="Senior Data Engineer")], "t", 1, 0)
    assert (s1["inserted"], s1["updated"]) == (1, 0) and (s2["inserted"], s2["updated"]) == (0, 1)
    with conn.cursor() as cur:
        cur.execute("select count(*) from jobs"); assert cur.fetchone()[0] == 1
        cur.execute("select title from jobs"); assert cur.fetchone()[0] == "Senior Data Engineer"
        cur.execute("select count(*) from job_skills"); assert cur.fetchone()[0] == 2
        cur.execute("select count(*) from companies"); assert cur.fetchone()[0] == 1
