#!/usr/bin/env python3
"""Send personalized task-3 fix hints to failing students via Telegram.

Categorizes each student's latest task-3 result and sends a targeted message
with specific commands to fix their issue.

Usage:
    # Dry run (show what would be sent)
    python scripts/send_task3_hints.py --dry-run

    # Actually send messages
    python scripts/send_task3_hints.py

    # Run inside the bot container on Hetzner:
    docker exec autochecker-bot python3 scripts/send_task3_hints.py --dry-run
"""

import argparse
import asyncio
import json
import os
import sqlite3
import sys

HINTS = {
    "agent_not_found": (
        "🔧 *Task 3 hint: agent\\.py not found on your VM*\n\n"
        "The autochecker connects to your VM and looks for `~/se\\-toolkit\\-lab\\-6/agent\\.py`\\. "
        "It can't find it\\. Common causes:\n\n"
        "1\\. *Repo not cloned* in the right place:\n"
        "```\n"
        "cd ~ && git clone https://github.com/YOUR_USERNAME/se-toolkit-lab-6.git\n"
        "cd ~/se-toolkit-lab-6 && uv sync\n"
        "```\n\n"
        "2\\. *SSH key not set up* for your vm\\_username\\. Run this as root on your VM:\n"
        "```\n"
        "mkdir -p ~/.ssh && chmod 700 ~/.ssh\n"
        "echo 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKiL0DDQZw7L0Uf1c9cNlREY7IS6ZkIbGVWNsClqGNCZ se-toolkit-autochecker' >> ~/.ssh/authorized_keys\n"
        "chmod 600 ~/.ssh/authorized_keys\n"
        "```\n"
        "If your `vm_username` is different from root, run the same commands as that user\\.\n\n"
        "3\\. *Home directory is world\\-writable* \\(chmod 777\\)\\. SSH rejects key auth if `~` is 777\\. Fix:\n"
        "```\nchmod 755 ~\n```\n\n"
        "Try again after fixing — press Start, choose Lab 6, then Task 3\\."
    ),

    "crash": (
        "🔧 *Task 3 hint: agent crashes \\(exit code 1\\)*\n\n"
        "Your agent starts but crashes during execution\\. Debug steps:\n\n"
        "1\\. *Test manually* on your VM:\n"
        "```\n"
        "cd ~/se-toolkit-lab-6\n"
        "uv sync\n"
        "set -a && . <(tr -d '\\r' < .env.agent.secret) && set +a\n"
        "uv run agent.py \"What is 2+2?\"\n"
        "```\n\n"
        "2\\. *Common causes:*\n"
        "• `ModuleNotFoundError` → run `uv sync`\n"
        "• API errors → check values in `\\.env\\.agent\\.secret`\n"
        "• `Connection refused` → your Qwen proxy isn't running\\. Check `docker ps`\n"
        "• Windows line endings → `sed \\-i 's/\\\\r$//' \\.env\\.agent\\.secret`\n\n"
        "Read the error message when you run it manually — it will tell you exactly what's wrong\\."
    ),

    "invalid_json": (
        "🔧 *Task 3 hint: Invalid JSON output*\n\n"
        "Your agent must print exactly one valid JSON object to stdout\\. "
        "All debug output must go to stderr\\.\n\n"
        "Fix:\n"
        "• Final answer: `print\\(json\\.dumps\\(result\\)\\)`\n"
        "• Debug logs: `print\\(\"debug\\.\\.\\.\"\\, file=sys\\.stderr\\)`\n\n"
        "Test:\n"
        "```\n"
        "uv run agent.py \"What is 2+2?\" 2>/dev/null | python3 -m json.tool\n"
        "```\n"
        "This should show valid JSON\\. If not, you have extra print statements going to stdout\\."
    ),

    "eval_fail": (
        "🔧 *Task 3 hint: agent doesn't pass eval questions*\n\n"
        "Your agent runs but doesn't answer correctly\\. Steps to improve:\n\n"
        "1\\. *Run the local eval yourself:*\n"
        "```\n"
        "cd ~/se-toolkit-lab-6\n"
        "set -a && . <(tr -d '\\r' < .env.agent.secret) && set +a\n"
        "uv run run_eval.py\n"
        "```\n\n"
        "2\\. Check which question classes fail \\(factual, analytical, tool\\-use, reasoning, comparison\\) "
        "and improve your agent's logic for those\\.\n\n"
        "3\\. Make sure your agent can:\n"
        "• Read wiki files from the repo\n"
        "• Call the backend API via `query_api` tool\n"
        "• Reason about the answer before responding\n\n"
        "The local eval has 5 open questions \\(1 per class\\)\\. Fix those first — "
        "the hidden eval uses the same question classes\\."
    ),
}


def categorize(details_json: str) -> str:
    """Categorize the failure based on check results."""
    try:
        checks = json.loads(details_json)
    except (json.JSONDecodeError, TypeError):
        return "other"

    if not isinstance(checks, list):
        return "other"

    all_pass = all(c.get("status") == "PASS" for c in checks)
    if all_pass:
        return "pass"

    all_details = " ".join(str(c.get("details", "")) for c in checks)

    if "Could not find agent.py" in all_details:
        return "agent_not_found"
    if "exited with code 1" in all_details or "exit code 1" in all_details.lower():
        return "crash"
    if "Invalid JSON" in all_details:
        return "invalid_json"
    if any(c.get("status") == "FAIL" for c in checks):
        return "eval_fail"

    return "other"


def get_failing_students(db_path: str):
    """Get latest task-3 result for each student, categorized."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""
        SELECT r.tg_id, r.details, u.tg_username, u.github_alias
        FROM results r
        JOIN users u ON r.tg_id = u.tg_id
        WHERE r.lab_id = 'lab-06' AND r.task_id = 'task-3'
        AND r.id IN (
            SELECT MAX(id) FROM results
            WHERE lab_id = 'lab-06' AND task_id = 'task-3'
            GROUP BY tg_id
        )
    """)
    students = {}
    for tg_id, details, tg_username, github_alias in c.fetchall():
        cat = categorize(details)
        if cat not in ("pass", "other"):
            students[tg_id] = {
                "tg_id": tg_id,
                "tg_username": tg_username,
                "github_alias": github_alias,
                "category": cat,
            }
    conn.close()
    return students


async def send_messages(students: dict, dry_run: bool = True):
    """Send hint messages to students."""
    if not dry_run:
        from aiogram import Bot
        bot_token = os.environ.get("BOT_TOKEN")
        if not bot_token:
            print("ERROR: BOT_TOKEN not set", file=sys.stderr)
            sys.exit(1)
        bot = Bot(token=bot_token)

    counts = {}
    for s in students.values():
        cat = s["category"]
        counts[cat] = counts.get(cat, 0) + 1
        hint_text = HINTS.get(cat)
        if not hint_text:
            continue

        if dry_run:
            print(f"[DRY RUN] Would send to @{s['tg_username']} ({s['github_alias']}, tg_id={s['tg_id']}): [{cat}]")
        else:
            try:
                await bot.send_message(s["tg_id"], hint_text, parse_mode="MarkdownV2")
                print(f"Sent [{cat}] to @{s['tg_username']} ({s['github_alias']})")
            except Exception as e:
                print(f"Failed to send to @{s['tg_username']}: {e}")
            await asyncio.sleep(0.1)  # rate limit

    if not dry_run:
        await bot.session.close()

    print(f"\nSummary: {sum(counts.values())} students")
    for cat, count in sorted(counts.items()):
        print(f"  {cat}: {count}")


def main():
    parser = argparse.ArgumentParser(description="Send personalized task-3 hints to failing students")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be sent without sending")
    parser.add_argument("--db", help="Path to bot.db", default="")
    args = parser.parse_args()

    db_path = args.db
    if not db_path:
        for p in [os.environ.get("DB_PATH", ""), "/app/data/bot.db",
                   os.path.join(os.path.dirname(__file__), "..", "data", "bot.db")]:
            if p and os.path.exists(p):
                db_path = p
                break

    if not db_path or not os.path.exists(db_path):
        print("ERROR: Database not found. Set DB_PATH or use --db.", file=sys.stderr)
        sys.exit(1)

    students = get_failing_students(db_path)
    asyncio.run(send_messages(students, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
