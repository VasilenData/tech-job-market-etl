-- Normalized schema (3NF-ish). Idempotent: safe to run on every pipeline run.
CREATE TABLE IF NOT EXISTS companies (
    company_id  SERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS jobs (
    job_id        TEXT PRIMARY KEY,                 -- "<source>:<source id>"
    source        TEXT NOT NULL,
    title         TEXT NOT NULL,
    company_id    INT  NOT NULL REFERENCES companies,
    location      TEXT,
    is_remote     BOOLEAN NOT NULL,
    job_type      TEXT,
    role_family   TEXT NOT NULL,                    -- data_engineering | data_analytics | data_science_ml | software | other
    url           TEXT,
    posted_at     TIMESTAMPTZ,
    first_seen_on DATE NOT NULL,
    last_seen_on  DATE NOT NULL
);
CREATE TABLE IF NOT EXISTS skills (
    skill_id SERIAL PRIMARY KEY,
    name     TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS job_skills (
    job_id   TEXT NOT NULL REFERENCES jobs ON DELETE CASCADE,
    skill_id INT  NOT NULL REFERENCES skills,
    PRIMARY KEY (job_id, skill_id)
);
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id       SERIAL PRIMARY KEY,
    run_date     DATE NOT NULL,
    source       TEXT NOT NULL,
    fetched      INT NOT NULL,
    valid        INT NOT NULL,
    rejected     INT NOT NULL,
    inserted     INT NOT NULL,
    updated      INT NOT NULL,
    logged_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS jobs_last_seen_idx ON jobs (last_seen_on);
CREATE INDEX IF NOT EXISTS jobs_family_idx ON jobs (role_family);
