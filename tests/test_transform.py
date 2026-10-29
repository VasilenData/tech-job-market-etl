from pipeline.transform import classify_role, clean, extract_skills, normalize_arbeitnow, normalize_remotive, strip_html


def test_classify_role():
    assert classify_role("Senior Data Engineer (m/f/d)") == "data_engineering"
    assert classify_role("Analytics Engineer") == "data_engineering"
    assert classify_role("Machine Learning Scientist") == "data_science_ml"
    assert classify_role("Business Intelligence Analyst") == "data_analytics"
    assert classify_role("Backend Developer") == "software"
    assert classify_role("Office Manager") == "other"


def test_extract_skills_handles_html_and_word_boundaries():
    s = extract_skills("<p>We use <b>Python</b>, SQL and dbt on Snowflake</p>", "JavaScript and Airflow")
    assert set(s) == {"Python", "SQL", "dbt", "Snowflake", "Airflow"}
    assert "Java" not in extract_skills("We love JavaScript")


def test_strip_html():
    assert strip_html("<p>a &amp; b</p>\n<p>c</p>") == "a & b c"


def test_normalizers():
    a = normalize_arbeitnow({"slug": "x-1", "title": " Data Engineer ", "company_name": "Acme", "remote": True,
                             "location": "Berlin", "created_at": 1760000000, "job_types": ["full time"], "description": "python", "tags": []})
    assert a["job_id"] == "arbeitnow:x-1" and a["title"] == "Data Engineer" and a["is_remote"] and a["posted_at"].startswith("2025")
    r = normalize_remotive({"id": 5, "title": "ML Engineer", "company_name": "Foo", "publication_date": "2026-10-26T12:20:09",
                            "candidate_required_location": "Worldwide", "job_type": "full_time", "tags": ["AI/ML"], "description": ""})
    assert r["job_id"] == "remotive:5" and r["is_remote"] and r["location"] == "Worldwide"


def test_clean_rejects_bad_rows_and_dedupes():
    base = {"source": "t", "location": None, "is_remote": False, "job_type": None, "url": None, "posted_at": None, "skills": []}
    rows = [{**base, "job_id": "t:1", "title": "Data Engineer", "company": "A"},
            {**base, "job_id": "t:1", "title": "Data Engineer v2", "company": "A"},   # duplicate id, keep latest
            {**base, "job_id": "t:2", "title": "", "company": "A"},                    # missing title
            {**base, "job_id": "t:3", "title": "Analyst", "company": ""},              # missing company
            {**base, "job_id": "t:None", "title": "X", "company": "A"}]                # missing id
    good, rejects = clean(rows)
    assert [g["title"] for g in good] == ["Data Engineer v2"]
    assert len(rejects) == 3 and good[0]["role_family"] == "data_engineering"
