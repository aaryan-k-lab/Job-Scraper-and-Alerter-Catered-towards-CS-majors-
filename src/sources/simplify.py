"""Fetch and parse listings.json from the SimplifyJobs Summer2027-Internships repo."""

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

LISTINGS_URL = (
    "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/"
    "dev/.github/scripts/listings.json"
)

US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA",
    "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT",
    "VA", "WA", "WV", "WI", "WY", "DC", "PR",
}
US_WORDS = {"usa", "us", "united states", "nyc", "sf", "la", "remote", "remote in usa", "remote in us"}


@dataclass
class Listing:
    simplify_id: str
    company: str
    title: str
    url: str
    locations: list[str]
    terms: list[str]
    category: str
    date_posted: int
    sponsorship: str = "Other"
    degrees: list[str] = field(default_factory=list)


def fetch(cache_dir: Path, url: str = LISTINGS_URL) -> list[dict]:
    """Download listings.json, re-using the cached copy when GitHub says it hasn't changed."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / "listings.json"
    etag_file = cache_dir / "listings.etag"

    req = urllib.request.Request(url)
    if cache.exists() and etag_file.exists():
        req.add_header("If-None-Match", etag_file.read_text().strip())
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            cache.write_bytes(resp.read())
            if resp.headers.get("ETag"):
                etag_file.write_text(resp.headers["ETag"])
            log.info("Downloaded fresh listings.json")
    except urllib.error.HTTPError as e:
        if e.code != 304:
            raise
        log.info("listings.json unchanged; using cache")
    except urllib.error.URLError as e:
        if not cache.exists():
            raise
        log.warning("Fetch failed (%s); using cached listings.json", e.reason)

    with open(cache, encoding="utf-8") as f:
        return json.load(f)


def is_us_location(loc: str) -> bool:
    s = loc.strip()
    if s.lower() in US_WORDS:
        return True
    parts = [p.strip() for p in s.split(",")]
    # "City, ST" (Canada etc. come as "City, ON, Canada", so the last part isn't a state)
    return len(parts) >= 2 and parts[-1].upper() in US_STATES


def parse(raw: list[dict], terms: list[str], us_only: bool) -> list[Listing]:
    """Keep active, visible listings for the wanted terms (and US locations if us_only)."""
    wanted = set(terms)
    out = []
    counts = {"inactive": 0, "wrong_term": 0, "non_us": 0}
    for x in raw:
        if not (x.get("active") and x.get("is_visible", True)):
            counts["inactive"] += 1
            continue
        if not wanted.intersection(x.get("terms", [])):
            counts["wrong_term"] += 1
            continue
        locations = x.get("locations") or []
        if us_only and locations and not any(is_us_location(l) for l in locations):
            counts["non_us"] += 1
            continue
        out.append(Listing(
            simplify_id=x["id"],
            company=x["company_name"].strip(),
            title=x["title"].strip(),
            url=x["url"].strip(),
            locations=locations,
            terms=x.get("terms", []),
            category=x.get("category", ""),
            date_posted=int(x.get("date_posted", 0)),
            sponsorship=x.get("sponsorship", "Other"),
            degrees=x.get("degrees") or [],
        ))
    log.info("Parsed %d listings; dropped %s", len(out), counts)
    return out
