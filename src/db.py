"""SQLite job queue and application log."""

import json
import sqlite3
import time
from pathlib import Path

STATUSES = ("queued", "filled", "awaiting_review", "submitted", "skipped", "failed")
# Statuses a re-sync may overwrite. Anything else means we've touched the application.
RESYNCABLE = ("queued", "skipped")

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id            INTEGER PRIMARY KEY,
    dedup_key     TEXT UNIQUE NOT NULL,
    simplify_id   TEXT,
    company       TEXT NOT NULL,
    title         TEXT NOT NULL,
    url           TEXT NOT NULL,
    locations     TEXT,
    terms         TEXT,
    category      TEXT,
    date_posted   INTEGER,
    ats           TEXT,
    tier          INTEGER,
    role_bucket   TEXT,
    score         REAL,
    score_reasons TEXT,
    status        TEXT NOT NULL DEFAULT 'queued',
    status_reason TEXT,
    created_at    INTEGER NOT NULL,
    updated_at    INTEGER NOT NULL,
    submitted_at  INTEGER
);
"""


def connect(path: Path | str) -> sqlite3.Connection:
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def upsert(conn: sqlite3.Connection, job: dict) -> str:
    """Insert a job or refresh it. Returns 'inserted', 'updated', or 'kept' (already worked on)."""
    now = int(time.time())
    row = conn.execute("SELECT status FROM jobs WHERE dedup_key = ?", (job["dedup_key"],)).fetchone()
    fields = {
        **job,
        "locations": json.dumps(job.get("locations", [])),
        "terms": json.dumps(job.get("terms", [])),
        "score_reasons": "; ".join(job.get("score_reasons", [])),
        "updated_at": now,
    }
    if row is None:
        fields["created_at"] = now
        cols = ", ".join(fields)
        conn.execute(f"INSERT INTO jobs ({cols}) VALUES ({', '.join('?' * len(fields))})", list(fields.values()))
        return "inserted"
    if row["status"] not in RESYNCABLE:
        return "kept"
    sets = ", ".join(f"{k} = ?" for k in fields if k != "dedup_key")
    conn.execute(f"UPDATE jobs SET {sets} WHERE dedup_key = ?",
                 [v for k, v in fields.items() if k != "dedup_key"] + [job["dedup_key"]])
    return "updated"


def mark_missing_closed(conn: sqlite3.Connection, live_keys: set[str]) -> int:
    """Queued jobs that vanished from the active listings get skipped as closed."""
    queued = [r["dedup_key"] for r in conn.execute("SELECT dedup_key FROM jobs WHERE status = 'queued'")]
    gone = [k for k in queued if k not in live_keys]
    for k in gone:
        set_status(conn, k, "skipped", "closed")
    return len(gone)


def set_status(conn: sqlite3.Connection, dedup_key: str, status: str, reason: str | None = None) -> None:
    assert status in STATUSES, status
    now = int(time.time())
    conn.execute(
        "UPDATE jobs SET status = ?, status_reason = ?, updated_at = ?, "
        "submitted_at = CASE WHEN ? = 'submitted' THEN ? ELSE submitted_at END WHERE dedup_key = ?",
        (status, reason, now, status, now, dedup_key),
    )


def ranked(conn: sqlite3.Connection, statuses=("queued",), tier: int | None = None, limit: int = 20):
    """Tier 1 first, then by score."""
    q = f"SELECT * FROM jobs WHERE status IN ({', '.join('?' * len(statuses))})"
    args: list = list(statuses)
    if tier is not None:
        q += " AND tier = ?"
        args.append(tier)
    q += " ORDER BY (tier = 1) DESC, score DESC, date_posted DESC LIMIT ?"
    return conn.execute(q, args + [limit]).fetchall()


def status_counts(conn: sqlite3.Connection) -> dict:
    return {f"{r[0]}" + (f" ({r[1]})" if r[1] else ""): r[2] for r in conn.execute(
        "SELECT status, status_reason, COUNT(*) FROM jobs GROUP BY status, status_reason ORDER BY 3 DESC")}
