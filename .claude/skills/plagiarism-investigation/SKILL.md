# Skill: Plagiarism Investigation

Investigate suspected plagiarism between student lab submissions.

## Trigger

When the user asks to check plagiarism, investigate suspicious pairs, or run plagiarism screening.

## Workflow

### 1. Automated Screening (batch)

Run on the deploy server. Do NOT use OpenRouter — only code-similarity.

```bash
# Get student list from bot DB (adapt SSH target to your deploy host)
ssh $DEPLOY_USER@$DEPLOY_HOST "docker exec autochecker-bot python3 -c \"
import sqlite3
conn = sqlite3.connect('/app/data/bot.db')
for r in conn.execute('SELECT DISTINCT github_alias FROM users WHERE github_alias != \\\"\\\"').fetchall():
    print(r[0])
\"" > /tmp/students_plag.txt

echo "student_alias" > /tmp/students_plag.csv
cat /tmp/students_plag.txt >> /tmp/students_plag.csv
scp /tmp/students_plag.csv $DEPLOY_USER@$DEPLOY_HOST:/tmp/students_plag.csv
ssh $DEPLOY_USER@$DEPLOY_HOST "docker cp /tmp/students_plag.csv autochecker-bot:/tmp/students_plag.csv"

# Run batch WITHOUT LLM (unset OPENROUTER_API_KEY)
ssh $DEPLOY_USER@$DEPLOY_HOST "nohup docker exec -e OPENROUTER_API_KEY= autochecker-bot python3 -m autochecker batch \
  -s /tmp/students_plag.csv -l <lab-id> -p github \
  --plagiarism --threshold 0.5 \
  --template-repo <org>/<repo-name> \
  -w 2 > /tmp/plag-<lab-id>.log 2>&1 &"
```

The tool downloads each repo, hashes files (excluding template-identical ones), flags pairs above threshold, and scans git history for shared commits / cross-author emails.

Takes 30-60 min for ~250 students. Check progress: `grep -c '✅\|❌' /tmp/plag-<lab-id>.log`

Review `git_plagiarism_flags.json` — focus on **critical** (shared commit SHAs). High/medium flags are usually noise.

### 2. Deep Pair Investigation

For each flagged pair, clone and compare:

```bash
python scripts/investigate_pair.py \
  --student-a <name> --student-b <name> \
  --repo <repo-name> \
  --template <org>/<repo-name> \
  --output /tmp/plag-<lab-id>/investigations
```

This produces: file categorization, git timeline, cross-author analysis, source diffs.

### 3. Core File Analysis

Identify files students must write from scratch (not template / only stubs). Only these matter.

Compare core files byte-by-byte across flagged students. Identical non-trivial code = strong signal.

Ignore:
- Files identical to template (expected)
- Config files (.env, config.json — naturally similar)
- `.claude/` directories and AI scaffolding
- Prescribed commit messages from lab instructions

### 4. Context Signals

For each flagged pair check:
- **Git timeline**: Who committed first? Synchronized timestamps?
- **Commit authors**: Does A's repo contain B's commits? Cross-author emails?
- **PR reviews**: Did they review each other's code?
- **Autochecker attempts**: Synchronized checking patterns? (`bot.db` → attempts table)
- **Same group?**: Same lab group = same TA, same room
- **AI determinism**: At temperature > 0, LLM output is non-deterministic. Byte-identical code cannot come from independent AI runs.

### 5. Report

Write report to the private `autochecker-ops` repo under `reports/plagiarism-<lab-id>-<date>.md` with:

1. Methodology (which steps were run)
2. Screening results (total scanned, flags, errors)
3. Per-cluster findings:
   - File comparison table (core files: IDENTICAL / DIFFERENT)
   - Git timeline table (timestamps, authors)
   - Awareness analysis (who likely copied from whom)
   - Verdict: **CONFIRMED** / **SUSPECTED** / **CLEARED**

### 6. VM Repo Ownership Check (supplementary)

Check if students deployed someone else's repo on their VM:

```bash
# Via relay — checks git remote URL on each student's VM
python scripts/check_repo_ownership.py
```

Or manually via the relay API for specific students.
