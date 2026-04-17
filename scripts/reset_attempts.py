#!/usr/bin/env python3
"""Reset attempt counters for a specific lab + task.

Deletes only from the `attempts` table (the counter that limits retries).
Does NOT touch the `results` table (submission history is preserved).

Usage:
    # Reset all students' attempts for lab-06 task-3
    python scripts/reset_attempts.py --lab lab-06 --task task-3

    # Dry run (show what would be deleted)
    python scripts/reset_attempts.py --lab lab-06 --task task-3 --dry-run

    # Reset for a specific student (by tg_id)
    python scripts/reset_attempts.py --lab lab-06 --task task-3 --tg-id 123456789

    # Run inside the bot container on Hetzner:
    docker exec autochecker-bot python3 scripts/reset_attempts.py --lab lab-06 --task task-3

Environment:
    DB_PATH: path to bot.db (default: /app/data/bot.db or ./data/bot.db)
"""

import argparse
import os
import sqlite3
import sys


def get_db_path():
    """Find the bot database."""
    for path in [
        os.environ.get("DB_PATH", ""),
        "/app/data/bot.db",
        os.path.join(os.path.dirname(__file__), "..", "data", "bot.db"),
    ]:
        if path and os.path.exists(path):
            return path
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Reset attempt counters for a lab task (preserves results)"
    )
    parser.add_argument("--lab", required=True, help="Lab ID, e.g. lab-06")
    parser.add_argument("--task", required=True, help="Task ID, e.g. task-3")
    parser.add_argument("--tg-id", type=int, help="Reset only this student (Telegram ID)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted without doing it")
    parser.add_argument("--db", help="Path to bot.db (overrides DB_PATH)")
    args = parser.parse_args()

    db_path = args.db or get_db_path()
    if not db_path or not os.path.exists(db_path):
        print(f"ERROR: Database not found. Set DB_PATH or use --db.", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Build query
    where = "lab_id = ? AND task_id = ?"
    params = [args.lab, args.task]
    if args.tg_id:
        where += " AND tg_id = ?"
        params.append(args.tg_id)

    # Show what will be affected
    c.execute(f"SELECT COUNT(*) FROM attempts WHERE {where}", params)
    attempt_count = c.fetchone()[0]

    c.execute(f"SELECT COUNT(DISTINCT tg_id) FROM attempts WHERE {where}", params)
    student_count = c.fetchone()[0]

    # Also show results count (NOT being deleted) for safety confirmation
    c.execute(f"SELECT COUNT(*) FROM results WHERE {where}", params)
    result_count = c.fetchone()[0]

    scope = f"{args.lab} / {args.task}"
    if args.tg_id:
        scope += f" / tg_id={args.tg_id}"

    print(f"Scope: {scope}")
    print(f"  Attempts to delete: {attempt_count} (from {student_count} students)")
    print(f"  Results preserved:  {result_count} (NOT touched)")

    if attempt_count == 0:
        print("\nNothing to reset.")
        sys.exit(0)

    if args.dry_run:
        print("\n[DRY RUN] No changes made.")
        sys.exit(0)

    # Delete attempts only
    c.execute(f"DELETE FROM attempts WHERE {where}", params)
    conn.commit()
    deleted = c.rowcount

    print(f"\nDeleted {deleted} attempt records.")
    print(f"Results table untouched ({result_count} records preserved).")
    conn.close()


if __name__ == "__main__":
    main()
