#!/bin/bash
# Second-pass check: walk commits + PRs for repos where the fork compare returned null.
# Detects FAKE_PRS (PRs exist but none touch lab files) and EMPTY (no student commits).
#
# Usage:
#   scripts/recheck_null_repos.sh <lab-number>
#
# Reads from /tmp/lab${LAB_NUM}-empty-check.csv (output of check_empty_repos.sh)
# Writes to /tmp/lab${LAB_NUM}-recheck.csv
#
# Verdicts:
# - EMPTY:          0 student commits → no work
# - FAKE_PRS:       PRs exist but 0 of them touch lab core files
# - HAS_WORK:       real student commits + real lab files in PRs
# - DIRECT_COMMITS: student commits but no PRs (committed straight to main)

set -euo pipefail

LAB_NUM="${1:?Usage: $0 <lab-number>}"
INPUT="/tmp/lab${LAB_NUM}-empty-check.csv"
OUT="/tmp/lab${LAB_NUM}-recheck.csv"

REPO="se-toolkit-lab-${LAB_NUM}"
# Lab core file patterns — adjust per lab if needed
CORE_PATTERN="nanobot/|mcp/|docker-compose|caddy/Caddyfile|backend/.*\\.py$"
# Template authors to filter out
TEMPLATE_AUTHORS_RE="danila|nursultan|abuhopeful|egor dmitriev|deemp"

echo "github_alias,total_commits,student_commits,prs,real_pr_files,verdict" > "$OUT"

awk -F, '$NF=="HAS_WORK" && $2=="null" {print $1}' "$INPUT" | while read -r student; do
    [ -z "$student" ] && continue

    commits=$(gh api "repos/${student}/${REPO}/commits?per_page=100&sha=main" \
              --jq '.[].commit.author.name' 2>/dev/null || true)

    if [ -z "$commits" ]; then
        echo "${student},,,,,REPO_INACCESSIBLE" >> "$OUT"
        continue
    fi

    total=$(echo "$commits" | wc -l | tr -d ' ')
    student_commits=$(echo "$commits" | grep -viE "$TEMPLATE_AUTHORS_RE" | wc -l | tr -d ' ')

    prs=$(gh api "repos/${student}/${REPO}/pulls?state=all&per_page=100" --jq 'length' 2>/dev/null || echo 0)
    [ -z "$prs" ] && prs=0

    real_pr_files=0
    if [ "$prs" != "0" ]; then
        pr_numbers=$(gh api "repos/${student}/${REPO}/pulls?state=all&per_page=100" --jq '.[].number' 2>/dev/null || true)
        for pr in $pr_numbers; do
            [ -z "$pr" ] && continue
            files=$(gh api "repos/${student}/${REPO}/pulls/${pr}/files" \
                    --jq "[.[] | select(.filename | test(\"${CORE_PATTERN}\"))] | length" 2>/dev/null || echo 0)
            [[ "$files" =~ ^[0-9]+$ ]] || files=0
            real_pr_files=$((real_pr_files + files))
        done
    fi

    if [ "$student_commits" = "0" ]; then
        verdict="EMPTY"
    elif [ "$real_pr_files" = "0" ] && [ "$prs" != "0" ]; then
        verdict="FAKE_PRS"
    elif [ "$prs" = "0" ] && [ "$student_commits" -gt "0" ]; then
        verdict="DIRECT_COMMITS"
    else
        verdict="HAS_WORK"
    fi

    echo "${student},${total},${student_commits},${prs},${real_pr_files},${verdict}" >> "$OUT"
done

echo "Wrote $OUT"
