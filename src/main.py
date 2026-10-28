"""CLI entry point.

    uv run python -m src.main rank [--limit 20] [--tier 1] [--all]
"""

import argparse
import logging
import sys
import time
from datetime import date, datetime

from src import db
from src.config import DATA_DIR, LOGS_DIR, load_settings, load_targets
from src.dedup import dedup_key, detect_ats
from src.scoring import score
from src.sources import simplify

log = logging.getLogger("jobautoapplier")


def setup_logging() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(LOGS_DIR / f"run_{date.today():%Y%m%d}.log", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    logging.basicConfig(level=logging.DEBUG, handlers=[file_handler, console],
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def sync(conn, settings: dict, targets: dict) -> None:
    """Fetch listings, score them, and update the queue."""
    raw = simplify.fetch(DATA_DIR)
    listings = simplify.parse(raw, settings["terms"], settings["us_only"])
    now = time.time()
    seen: set[str] = set()
    stats = {"inserted": 0, "updated": 0, "kept": 0, "duplicate": 0}

    for li in listings:
        key = dedup_key(li.company, li.url)
        if key in seen:
            stats["duplicate"] += 1
            log.debug("Duplicate listing %s (%s - %s)", key, li.company, li.title)
            continue
        seen.add(key)

        pts, tier, bucket, reasons = score(li, settings, targets, now)
        ats = detect_ats(li.url)
        if bucket is None:
            status, reason = "skipped", "no_role_match"
        elif pts < settings["score_threshold"]:
            status, reason = "skipped", "below_threshold"
        elif ats is None:
            status, reason = "skipped", "unsupported_ats"
        else:
            status, reason = "queued", None

        result = db.upsert(conn, {
            "dedup_key": key, "simplify_id": li.simplify_id, "company": li.company, "title": li.title,
            "url": li.url, "locations": li.locations, "terms": li.terms, "category": li.category,
            "date_posted": li.date_posted, "ats": ats, "tier": tier, "role_bucket": bucket,
            "score": pts, "score_reasons": reasons, "status": status, "status_reason": reason,
        })
        stats[result] += 1
        log.debug("%s | %s - %s | score=%s [%s] -> %s%s", result, li.company, li.title, pts,
                  "; ".join(reasons), status, f" ({reason})" if reason else "")

    closed = db.mark_missing_closed(conn, seen)
    conn.commit()
    log.info("Sync: %s, newly closed=%d", stats, closed)


def print_ranked(rows) -> None:
    if not rows:
        print("No jobs match.")
        return
    print(f"\n{'#':>3}  {'Score':>5}  T  {'ATS':<10}  {'Posted':<10}  {'Company':<24}  Title")
    for i, r in enumerate(rows, 1):
        posted = datetime.fromtimestamp(r["date_posted"]).strftime("%Y-%m-%d")
        ats = r["ats"] or "-"
        print(f"{i:>3}  {r['score']:>5}  {r['tier']}  {ats:<10}  {posted:<10}  {r['company'][:24]:<24}  {r['title'][:60]}")
        if r["status"] != "queued":
            print(f"{'':>13}[{r['status']}: {r['status_reason']}]")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="jobautoapplier")
    sub = parser.add_subparsers(dest="command", required=True)
    rank = sub.add_parser("rank", help="Sync listings and print the top ranked jobs")
    rank.add_argument("--limit", type=int, default=20)
    rank.add_argument("--tier", type=int, choices=[1, 2, 3])
    rank.add_argument("--all", action="store_true",
                      help="Include jobs skipped for unsupported ATS (to apply manually)")
    args = parser.parse_args(argv)

    setup_logging()
    settings, targets = load_settings(), load_targets()
    conn = db.connect(DATA_DIR / "jobs.db")

    if args.command == "rank":
        sync(conn, settings, targets)
        statuses = ("queued", "skipped") if args.all else ("queued",)
        rows = db.ranked(conn, statuses, args.tier, args.limit)
        if args.all:
            rows = [r for r in rows if r["status"] == "queued" or r["status_reason"] == "unsupported_ats"]
        print_ranked(rows)
        print("\nQueue:", db.status_counts(conn))


if __name__ == "__main__":
    main()
