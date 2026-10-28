"""Score listings 0-100 from role fit, company tier, and recency."""

import re
import time

from src.dedup import normalize_company
from src.sources.simplify import Listing


def company_tier(company: str, targets: dict) -> int:
    """1, 2, or 3 (everything else)."""
    name = normalize_company(company)
    for tier in (1, 2):
        if name in {normalize_company(c) for c in targets[f"tier{tier}"]}:
            return tier
    return 3


def _has_word(text: str, phrase: str) -> bool:
    return re.search(rf"\b{re.escape(phrase)}\b", text, re.I) is not None


def role_bucket(title: str, settings: dict) -> str | None:
    """The first role bucket whose keywords appear in the title, or None."""
    if any(_has_word(title, kw) for kw in settings["negative_keywords"]):
        return None
    for bucket, keywords in settings["role_keywords"].items():
        if any(_has_word(title, kw) for kw in keywords):
            return bucket
    return None


def score(listing: Listing, settings: dict, targets: dict, now: float | None = None) -> tuple[float, int, str | None, list[str]]:
    """Return (score, tier, role_bucket, reasons)."""
    w = settings["weights"]
    now = time.time() if now is None else now
    reasons = []

    bucket = role_bucket(listing.title, settings)
    role_pts = w["role"] if bucket else 0
    reasons.append(f"role={bucket or 'none'} +{role_pts}")

    tier = company_tier(listing.company, targets)
    tier_pts = {1: w["tier"], 2: w["tier"] / 2, 3: 0}[tier]
    reasons.append(f"tier={tier} +{tier_pts:g}")

    age_days = max(0.0, (now - listing.date_posted) / 86400)
    recency_pts = w["recency"] * max(0.0, 1 - age_days / settings["recency_days"])
    reasons.append(f"age={age_days:.0f}d +{recency_pts:.1f}")

    return round(role_pts + tier_pts + recency_pts, 1), tier, bucket, reasons
