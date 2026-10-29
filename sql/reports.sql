-- Daily trend: jobs seen per day by role family (history accumulates via first_seen_on).
-- name: daily_postings
SELECT first_seen_on AS day, role_family, COUNT(*) AS new_jobs
FROM jobs GROUP BY 1, 2 ORDER BY 1, 2;

-- Currently active postings (seen on the latest run) by role family, with remote share.
-- name: active_by_family
SELECT role_family, COUNT(*) AS active_jobs,
       ROUND(100.0 * AVG(is_remote::int), 1) AS remote_pct
FROM jobs WHERE last_seen_on = (SELECT MAX(last_seen_on) FROM jobs)
GROUP BY role_family ORDER BY active_jobs DESC;

-- Most requested skills among active data-engineering roles.
-- name: top_skills_data_engineering
SELECT s.name AS skill, COUNT(*) AS jobs
FROM jobs j JOIN job_skills js USING (job_id) JOIN skills s USING (skill_id)
WHERE j.role_family = 'data_engineering' AND j.last_seen_on = (SELECT MAX(last_seen_on) FROM jobs)
GROUP BY s.name ORDER BY jobs DESC LIMIT 15;

-- Top hiring companies for data roles among active postings.
-- name: top_companies_data
SELECT c.name AS company, COUNT(*) AS open_roles
FROM jobs j JOIN companies c USING (company_id)
WHERE j.role_family IN ('data_engineering','data_analytics','data_science_ml')
  AND j.last_seen_on = (SELECT MAX(last_seen_on) FROM jobs)
GROUP BY c.name ORDER BY open_roles DESC, c.name LIMIT 10;
