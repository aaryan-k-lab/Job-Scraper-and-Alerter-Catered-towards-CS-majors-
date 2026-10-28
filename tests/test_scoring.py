from src.config import load_settings
from src.scoring import company_tier, role_bucket, score
from src.sources.simplify import Listing, is_us_location, parse

SETTINGS = load_settings()
TARGETS = {"tier1": ["Google", "Jane Street"], "tier2": ["Stripe"]}
NOW = 1_800_000_000.0
DAY = 86400


def make(title="Software Engineer Intern", company="Acme", age_days=0, **kw):
    return Listing(simplify_id="x", company=company, title=title, url="https://jobs.lever.co/acme/1",
                   locations=["Austin, TX"], terms=["Spring 2027"], category="Software",
                   date_posted=int(NOW - age_days * DAY), **kw)


def test_company_tier_ignores_case_and_suffixes():
    assert company_tier("Google LLC", TARGETS) == 1
    assert company_tier("jane street", TARGETS) == 1
    assert company_tier("Stripe, Inc.", TARGETS) == 2
    assert company_tier("Acme", TARGETS) == 3


def test_role_bucket():
    assert role_bucket("Software Engineer Intern", SETTINGS) == "swe"
    assert role_bucket("Machine Learning Research Intern", SETTINGS) == "ai_ml"
    assert role_bucket("Data Scientist Intern", SETTINGS) == "data"
    assert role_bucket("IT Support Intern", SETTINGS) == "it"
    assert role_bucket("Mechanical Engineering Intern", SETTINGS) is None
    # negative keyword wins over a positive one
    assert role_bucket("Hardware Software Co-op", SETTINGS) is None
    # whole words only: "ai" must not match inside "Maintenance"
    assert role_bucket("Maintenance Intern", SETTINGS) is None


def test_score_components():
    w = SETTINGS["weights"]
    pts, tier, bucket, _ = score(make(company="Google"), SETTINGS, TARGETS, NOW)
    assert (pts, tier, bucket) == (w["role"] + w["tier"] + w["recency"], 1, "swe")

    pts, tier, _, _ = score(make(company="Stripe"), SETTINGS, TARGETS, NOW)
    assert pts == w["role"] + w["tier"] / 2 + w["recency"]


def test_recency_decays_to_zero():
    w = SETTINGS["weights"]
    fresh = score(make(age_days=0), SETTINGS, TARGETS, NOW)[0]
    half = score(make(age_days=SETTINGS["recency_days"] / 2), SETTINGS, TARGETS, NOW)[0]
    old = score(make(age_days=SETTINGS["recency_days"] * 3), SETTINGS, TARGETS, NOW)[0]
    assert fresh > half > old == w["role"]


def test_us_location():
    for loc in ["Austin, TX", "NYC", "SF", "Remote in USA", "Remote", "United States", "Washington, DC"]:
        assert is_us_location(loc), loc
    for loc in ["Toronto, ON, Canada", "London, UK", "Remote in Canada", "Bangalore, India"]:
        assert not is_us_location(loc), loc


def test_parse_filters_inactive_terms_and_non_us():
    base = {"id": "1", "company_name": "A", "title": "SWE", "url": "u", "active": True, "is_visible": True,
            "terms": ["Spring 2027"], "locations": ["Austin, TX"], "date_posted": 0}
    raw = [
        base,
        {**base, "id": "2", "active": False},
        {**base, "id": "3", "terms": ["Summer 2026"]},
        {**base, "id": "4", "locations": ["London, UK"]},
        {**base, "id": "5", "locations": ["London, UK", "NYC"]},  # one US location is enough
    ]
    kept = parse(raw, ["Winter 2026", "Spring 2027"], us_only=True)
    assert [l.simplify_id for l in kept] == ["1", "5"]
