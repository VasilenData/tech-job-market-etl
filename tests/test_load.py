"""Integration test against a real (embedded) PostgreSQL: loading twice must not duplicate rows."""
import os
import tempfile
import uuid
from datetime import date

import pytest

psycopg2 = pytest.importorskip("psycopg2")
from pipeline import load  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JOB = {"job_id": "t:1", "source": "t", "title": "Data Engineer", "company": "Acme", "location": "Berlin", "is_remote": True,
       "job_type": "full_time", "url": "http://x", "posted_at": "2026-01-01T00:00:00+00:00", "skills": ["Python", "SQL"], "role_family": "data_engineering"}


@pytest.fixture
def conn():
    dsn = os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        pgserver = pytest.importorskip("pgserver")
        dsn = pgserver.get_server(tempfile.mkdtemp()).get_uri()
    conn = psycopg2.connect(dsn)
    schema = "etl_test_" + uuid.uuid4().hex
    with conn.cursor() as cur:
        cur.execute(f'CREATE SCHEMA "{schema}"')
        cur.execute(f'SET search_path TO "{schema}"')
    conn.commit()
    with conn.cursor() as cur:
        cur.execute(open(os.path.join(ROOT, "sql", "schema.sql")).read())
    conn.commit()
    yield conn
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute(f'DROP SCHEMA "{schema}" CASCADE')
    conn.commit()
    conn.close()


def test_load_is_idempotent(conn):
    s1 = load.load(conn, [JOB], "t", 1, 0)
    s2 = load.load(conn, [dict(JOB, title="Senior Data Engineer")], "t", 1, 0)
    assert (s1["inserted"], s1["updated"]) == (1, 0) and (s2["inserted"], s2["updated"]) == (0, 1)
    with conn.cursor() as cur:
        cur.execute("select count(*) from jobs"); assert cur.fetchone()[0] == 1
        cur.execute("select title from jobs"); assert cur.fetchone()[0] == "Senior Data Engineer"
        cur.execute("select count(*) from job_skills"); assert cur.fetchone()[0] == 2
        cur.execute("select count(*) from companies"); assert cur.fetchone()[0] == 1


def test_reload_updates_company_date_and_replaces_removed_skills(conn):
    load.load(conn, [JOB], "t", 1, 0, today=date(2026, 1, 1))
    changed = dict(JOB, company="New company", posted_at="2026-01-02T00:00:00+00:00", skills=["dbt"])
    load.load(conn, [changed], "t", 1, 0, today=date(2026, 1, 2))
    with conn.cursor() as cur:
        cur.execute("select c.name, j.posted_at::date, first_seen_on, last_seen_on from jobs j join companies c using(company_id)")
        assert cur.fetchone() == ("New company", date(2026, 1, 2), date(2026, 1, 1), date(2026, 1, 2))
        cur.execute("select s.name from job_skills js join skills s using(skill_id)")
        assert cur.fetchall() == [("dbt",)]
    load.load(conn, [dict(changed, skills=[])], "t", 1, 0)
    with conn.cursor() as cur:
        cur.execute("select count(*) from job_skills")
        assert cur.fetchone()[0] == 0


def test_failed_reload_rolls_back_job_and_skill_replacement(conn):
    load.load(conn, [JOB], "t", 1, 0)
    with pytest.raises(psycopg2.Error):
        load.load(conn, [dict(JOB, title="Changed", skills=[None])], "t", 1, 0)
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute("select title from jobs")
        assert cur.fetchone()[0] == JOB["title"]
        cur.execute("select s.name from job_skills js join skills s using(skill_id) order by s.name")
        assert cur.fetchall() == [("Python",), ("SQL",)]



def test_same_day_refresh_replaces_membership_and_keeps_other_sources(conn):
    today = date(2026, 11, 11)
    second = dict(JOB, job_id="t:2")
    other = dict(JOB, job_id="other:1", source="other")
    load.load(conn, [JOB, second], "t", 2, 0, today=today)
    load.load(conn, [other], "other", 1, 0, today=today)
    load.load(conn, [second], "t", 1, 0, today=today)
    with conn.cursor() as cur:
        cur.execute("select job_id,in_latest_sample,last_seen_on from jobs order by job_id")
        assert cur.fetchall() == [("other:1", True, today), ("t:1", False, today), ("t:2", True, today)]
        cur.execute("select count(*) from jobs where in_latest_sample and last_seen_on=%s", (today,))
        assert cur.fetchone()[0] == 2
    load.load(conn, [JOB], "t", 1, 0, today=today)
    with conn.cursor() as cur:
        cur.execute("select first_seen_on,in_latest_sample from jobs where job_id='t:1'")
        assert cur.fetchone() == (today, True)


def test_failed_refresh_restores_previous_membership(conn):
    load.load(conn, [JOB, dict(JOB, job_id="t:2")], "t", 2, 0)
    with pytest.raises(psycopg2.Error):
        load.load(conn, [dict(JOB, skills=[None])], "t", 1, 0)
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute("select count(*) from jobs where in_latest_sample")
        assert cur.fetchone()[0] == 2


@pytest.mark.parametrize("jobs", [[], [dict(JOB, source="wrong")]])
def test_invalid_snapshot_cannot_clear_existing_membership(conn, jobs):
    load.load(conn, [JOB], "t", 1, 0)
    with pytest.raises(ValueError, match="nonempty"):
        load.load(conn, jobs, "t", len(jobs), 0)
    with conn.cursor() as cur:
        cur.execute("select in_latest_sample from jobs")
        assert cur.fetchone()[0] is True


def test_schema_upgrade_never_assumes_historical_rows_are_current(conn):
    load.load(conn, [JOB], "t", 1, 0)
    with conn.cursor() as cur:
        cur.execute("ALTER TABLE jobs DROP COLUMN in_latest_sample")
        with open(os.path.join(ROOT, "sql/schema.sql"), encoding="utf-8") as stream:
            cur.execute(stream.read())
        cur.execute("select in_latest_sample from jobs")
        assert cur.fetchone()[0] is False
    conn.commit()
    load.load(conn, [JOB], "t", 1, 0)
    with conn.cursor() as cur:
        cur.execute("select in_latest_sample from jobs")
        assert cur.fetchone()[0] is True
