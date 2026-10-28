"""Company-name normalization, URL cleanup, and ATS job-ID extraction for deduplication."""

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

COMPANY_SUFFIXES = {"inc", "llc", "ltd", "corp", "corporation", "co", "company", "plc", "lp", "llp"}
TRACKING_PARAMS = ("utm_", "ref", "source", "gh_src", "lever-source")


def normalize_company(name: str) -> str:
    words = re.sub(r"[^a-z0-9 ]", " ", name.lower().replace("&", " and ")).split()
    while words and words[-1] in COMPANY_SUFFIXES:
        words.pop()
    return " ".join(words)


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith(TRACKING_PARAMS)]
    path = re.sub(r"/application/?$", "", parts.path).rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def detect_ats(url: str) -> str | None:
    u = url.lower()
    if "greenhouse.io" in u or "gh_jid=" in u:
        return "greenhouse"
    if "jobs.lever.co" in u:
        return "lever"
    if "jobs.ashbyhq.com" in u:
        return "ashby"
    return None


def ats_job_id(url: str) -> str | None:
    """The ATS's own posting ID, so the same job via different URLs dedups."""
    ats = detect_ats(url)
    if ats == "greenhouse":
        m = re.search(r"gh_jid=(\d+)", url) or re.search(r"/jobs/(\d+)", url)
    elif ats in ("lever", "ashby"):
        m = re.search(r"/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", url, re.I)
    else:
        m = None
    return f"{ats}:{m.group(1).lower()}" if m else None


def dedup_key(company: str, url: str) -> str:
    return f"{normalize_company(company)}|{ats_job_id(url) or canonical_url(url)}"
