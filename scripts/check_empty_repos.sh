#!/bin/bash
# Check student repos for empty/no-implementation cases.
#
# Usage:
#   scripts/check_empty_repos.sh <lab-number> <student-list-file>
#
# Example:
#   scripts/check_empty_repos.sh 8 /tmp/lab08-students.txt
#
# Outputs CSV: github_alias,ahead_by,behind_by,prs,first_pr_files,verdict
# - HAS_WORK: fork is ahead of template (real or fake — verify with recheck script)
# - EMPTY:    fork is identical to template (no student commits)
# - REPO_NOT_FOUND: API returned no data
#
# Note: rows with ahead_by=null indicate the repo isn't a fork of the template
# (private, deleted+recreated, or independent push). Run recheck_null_repos.sh
# on those rows to determine whether they have real work or fake PRs.

set -euo pipefail

LAB_NUM="${1:?Usage: $0 <lab-number> <student-list-file>}"
STUDENT_LIST="${2:?Usage: $0 <lab-number> <student-list-file>}"
OUT="/tmp/lab${LAB_NUM}-empty-check.csv"

REPO="se-toolkit-lab-${LAB_NUM}"
TEMPLATE_OWNER="inno-se-toolkit"

echo "github_alias,ahead_by,behind_by,prs,first_pr_files,verdict" > "$OUT"

while read -r student; do
    [ -z "$student" ] && continue

    cmp=$(gh api "repos/${student}/${REPO}/compare/${TEMPLATE_OWNER}:main...main" \
          --jq '{ahead:.ahead_by,behind:.behind_by}' 2>/dev/null || true)

    if [ -z "$cmp" ]; then
        echo "${student},,,,,REPO_NOT_FOUND" >> "$OUT"
        continue
    fi

    ahead=$(echo "$cmp" | jq -r '.ahead')
    behind=$(echo "$cmp" | jq -r '.behind')

    if [ "$ahead" = "0" ]; then
        prs=$(gh api "repos/${student}/${REPO}/pulls?state=all&per_page=100" \
              --jq 'length' 2>/dev/null || echo 0)
        first_pr_files=""
        if [ "$prs" != "0" ] && [ -n "$prs" ]; then
            first_pr=$(gh api "repos/${student}/${REPO}/pulls?state=all&per_page=1" \
                       --jq '.[0].number' 2>/dev/null || true)
            if [ -n "$first_pr" ] && [ "$first_pr" != "null" ]; then
                first_pr_files=$(gh api "repos/${student}/${REPO}/pulls/${first_pr}/files" \
                                 --jq 'length' 2>/dev/null || echo 0)
            fi
        fi
        echo "${student},0,${behind},${prs},${first_pr_files},EMPTY" >> "$OUT"
    else
        echo "${student},${ahead},${behind},,,HAS_WORK" >> "$OUT"
    fi
done < "$STUDENT_LIST"

echo "Wrote $OUT"
