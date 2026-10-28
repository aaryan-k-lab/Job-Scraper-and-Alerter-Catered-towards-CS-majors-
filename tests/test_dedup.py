from src import db
from src.dedup import ats_job_id, canonical_url, dedup_key, detect_ats, normalize_company


def test_normalize_company():
    assert normalize_company("Google LLC") == normalize_company("google")
    assert normalize_company("Johnson & Johnson") == "johnson and johnson"
    assert normalize_company("Stripe, Inc.") == "stripe"


def test_canonical_url_strips_tracking_and_application_suffix():
    assert canonical_url("https://Example.com/jobs/1/?utm_source=Simplify&ref=Simplify") == "https://example.com/jobs/1"
    assert canonical_url("https://jobs.ashbyhq.com/acme/abc/application") == "https://jobs.ashbyhq.com/acme/abc"
    assert canonical_url("https://acme.com/careers?gh_jid=123&utm_source=x") == "https://acme.com/careers?gh_jid=123"


def test_detect_ats():
    assert detect_ats("https://job-boards.greenhouse.io/acme/jobs/123") == "greenhouse"
    assert detect_ats("https://boards.greenhouse.io/acme/jobs/123") == "greenhouse"
    assert detect_ats("https://acme.com/careers?gh_jid=123") == "greenhouse"
    assert detect_ats("https://jobs.lever.co/acme/0b1c2d3e-0000-4000-8000-000000000000") == "lever"
    assert detect_ats("https://jobs.ashbyhq.com/acme/0b1c2d3e-0000-4000-8000-000000000000") == "ashby"
    assert detect_ats("https://acme.wd1.myworkdayjobs.com/x") is None


def test_same_greenhouse_job_via_different_urls_dedups():
    a = "https://job-boards.greenhouse.io/acme/jobs/123?utm_source=Simplify"
    b = "https://boards.greenhouse.io/acme/jobs/123"
    c = "https://acme.com/careers?gh_jid=123"
    assert ats_job_id(a) == ats_job_id(b) == ats_job_id(c) == "greenhouse:123"
    assert dedup_key("Acme Inc", a) == dedup_key("acme", c)


def test_ashby_with_and_without_application_suffix_dedups():
    uid = "0b1c2d3e-0000-4000-8000-000000000000"
    assert dedup_key("Acme", f"https://jobs.ashbyhq.com/acme/{uid}") == \
        dedup_key("Acme", f"https://jobs.ashbyhq.com/acme/{uid}/application")


def _job(key="k1", **kw):
    return {"dedup_key": key, "company": "Acme", "title": "SWE", "url": "u", "score": 50,
            "status": "queued", **kw}


def test_db_upsert_never_duplicates_or_overwrites_applied_jobs():
    conn = db.connect(":memory:")
    assert db.upsert(conn, _job()) == "inserted"
    assert db.upsert(conn, _job(score=60)) == "updated"
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1

    db.set_status(conn, "k1", "submitted")
    assert db.upsert(conn, _job(score=10, status="queued")) == "kept"
    row = conn.execute("SELECT status, score, submitted_at FROM jobs").fetchone()
    assert row["status"] == "submitted" and row["score"] == 60 and row["submitted_at"]


def test_mark_missing_closed_only_touches_queued():
    conn = db.connect(":memory:")
    db.upsert(conn, _job("live"))
    db.upsert(conn, _job("gone"))
    db.upsert(conn, _job("applied"))
    db.set_status(conn, "applied", "awaiting_review")
    assert db.mark_missing_closed(conn, {"live"}) == 1
    statuses = dict(conn.execute("SELECT dedup_key, status FROM jobs").fetchall())
    assert statuses == {"live": "queued", "gone": "skipped", "applied": "awaiting_review"}


def test_ranked_puts_tier1_first():
    conn = db.connect(":memory:")
    db.upsert(conn, _job("a", tier=3, score=95))
    db.upsert(conn, _job("b", tier=1, score=45))
    db.upsert(conn, _job("c", tier=2, score=80))
    assert [r["dedup_key"] for r in db.ranked(conn)] == ["b", "a", "c"]
