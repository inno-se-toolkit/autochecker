#!/usr/bin/env python3
"""Check that repos on student VMs belong to the registered student.

For each student with a VM, SSH in and check git remote origin for
se-toolkit-lab-{4,5,6}. Flag mismatches where the repo belongs to
a different GitHub user.

Usage:
    docker exec autochecker-bot python3 scripts/check_repo_ownership.py
"""

import asyncio
import json
import os
import re
import sqlite3
import sys

import aiohttp

DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "http://dashboard:8000")
RELAY_TOKEN = os.environ.get("RELAY_TOKEN", "")
DB_PATH = os.environ.get("DB_PATH", "/app/data/bot.db")
REPOS = ["se-toolkit-lab-4", "se-toolkit-lab-5", "se-toolkit-lab-6"]

# Match GitHub username from remote URL:
#   https://github.com/USER/REPO.git
#   git@github.com:USER/REPO.git
REMOTE_RE = re.compile(r"github\.com[:/]([^/]+)/", re.IGNORECASE)


def get_students():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT tg_id, github_alias, vm_username, server_ip
        FROM users
        WHERE server_ip != '' AND server_ip IS NOT NULL
        ORDER BY github_alias
    """)
    students = [dict(r) for r in c.fetchall()]
    conn.close()
    return students


async def ssh_check(session, host, username, command, timeout=15):
    """Run SSH command via relay."""
    try:
        async with session.post(
            f"{DASHBOARD_URL}/relay/ssh",
            json={
                "type": "ssh",
                "host": host,
                "username": username,
                "command": command,
                "timeout": timeout,
            },
            headers={"Authorization": f"Bearer {RELAY_TOKEN}"},
            timeout=aiohttp.ClientTimeout(total=timeout + 10),
        ) as resp:
            return await resp.json()
    except Exception as e:
        return {"exit_code": -1, "stdout": "", "stderr": "", "error": str(e)}


async def check_student(session, student, semaphore):
    """Check all repos for one student."""
    alias = student["github_alias"]
    ip = student["server_ip"]
    username = student["vm_username"] or "root"
    findings = []

    # Skip non-internal IPs (can't reach via relay)
    if not ip.startswith("10."):
        return alias, findings, "skipped (public IP)"

    async with semaphore:
        # Single SSH command to check all repos at once.
        # Use GIT_CONFIG to bypass "dubious ownership" errors when
        # the repo was cloned by a different OS user.
        cmd_parts = []
        for repo in REPOS:
            cmd_parts.append(
                f"if [ -d ~/{repo}/.git ]; then"
                f" echo \"{repo}:$(GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=safe.directory GIT_CONFIG_VALUE_0='*'"
                f" git -C ~/{repo} remote get-url origin 2>/dev/null)\";"
                f" else echo \"{repo}:NOT_FOUND\"; fi"
            )
        cmd = " && ".join(cmd_parts)

        result = await ssh_check(session, ip, username, cmd)

        if result.get("exit_code") != 0:
            error = result.get("error") or result.get("stderr", "")
            if "Permission denied" in error or "Permission denied" in result.get("stderr", ""):
                return alias, findings, "SSH denied"
            return alias, findings, f"SSH error: {error[:80]}"

        stdout = result.get("stdout", "")
        for line in stdout.strip().split("\n"):
            if ":" not in line:
                continue
            repo, _, url = line.partition(":")
            repo = repo.strip()
            url = url.strip()

            if url == "NOT_FOUND":
                continue

            match = REMOTE_RE.search(url)
            if not match:
                findings.append((repo, "UNKNOWN_REMOTE", url))
                continue

            remote_user = match.group(1)
            if remote_user.lower() != alias.lower():
                findings.append((repo, remote_user, url))

    return alias, findings, "ok"


async def main():
    students = get_students()
    print(f"Checking {len(students)} students with VMs...\n")

    semaphore = asyncio.Semaphore(5)  # max 5 concurrent SSH
    flagged = []
    errors = []

    async with aiohttp.ClientSession() as session:
        tasks = [check_student(session, s, semaphore) for s in students]
        results = await asyncio.gather(*tasks)

    for alias, findings, status in results:
        if status != "ok":
            errors.append((alias, status))
        for repo, remote_user, url in findings:
            flagged.append((alias, repo, remote_user, url))

    # Print results
    if flagged:
        print("=" * 70)
        print("MISMATCHES FOUND")
        print("=" * 70)
        for alias, repo, remote_user, url in sorted(flagged):
            print(f"  {alias:30s} {repo:20s} -> {remote_user} ({url})")
        print(f"\nTotal: {len(flagged)} mismatch(es)\n")
    else:
        print("No mismatches found.\n")

    if errors:
        print(f"SSH errors ({len(errors)}):")
        for alias, status in sorted(errors):
            print(f"  {alias:30s} {status}")


if __name__ == "__main__":
    asyncio.run(main())
