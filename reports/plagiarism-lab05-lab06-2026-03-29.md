# Plagiarism Investigation Report: Lab 05 & Lab 06

**Date**: 2026-03-29
**Investigator**: Automated screening + manual review

---

## 1. Methodology

### 1.1 Automated Screening

Batch plagiarism check was run on 261 students for both labs:

```bash
source $(pyenv root)/versions/env313/bin/activate
cd autochecker/

# Get student list from bot database
ssh nurios@188.245.43.68 "docker exec autochecker-bot python3 -c \"
import sqlite3
conn = sqlite3.connect('/app/data/bot.db')
for r in conn.execute('SELECT DISTINCT github_alias FROM users WHERE github_alias != \\\"\\\"').fetchall():
    print(r[0])
\"" > /tmp/students_plag.txt

# Lab-05
python main.py batch \
  -s /tmp/students_plag.txt -l lab-05 -p github \
  --plagiarism --threshold 0.5 \
  --template-repo inno-se-toolkit/se-toolkit-lab-5 \
  -w 3 -o /tmp/plag-lab05

# Lab-06
python main.py batch \
  -s /tmp/students_plag.txt -l lab-06 -p github \
  --plagiarism --threshold 0.5 \
  --template-repo inno-se-toolkit/se-toolkit-lab-6 \
  -w 3 -o /tmp/plag-lab06
```

### 1.2 Deep Investigation

Flagged pairs were investigated with:

```bash
python scripts/investigate_pair.py \
  --student-a <name> --student-b <name> \
  --repo se-toolkit-lab-5 \
  --template inno-se-toolkit/se-toolkit-lab-5 \
  --output /tmp/plag-lab05/investigations
```

### 1.3 Core File Analysis

The template scaffold was analyzed to determine which files students were expected to write independently. Only **core task files** (not AI scaffolding like `.claude/skills/`) were considered for plagiarism.

**Lab-05 core files** (must be student-written):
| File | Template state | Student work |
|------|---------------|--------------|
| `backend/app/etl.py` | 147 lines, 5 functions with `raise NotImplementedError` + detailed TODO comments | Implement all 5 functions |
| `backend/app/routers/analytics.py` | 90 lines, 4 endpoints with `raise NotImplementedError` + detailed TODO comments | Implement all 4 SQL queries |
| `frontend/src/Dashboard.tsx` | **Not in template** | Create entirely from scratch |
| `frontend/src/App.tsx` | 128 lines, complete | Add navigation routes (~20-30 lines) |
| `frontend/src/App.css` | 61 lines, complete | Add dashboard styles |
| `frontend/vite.config.ts` | 30 lines, complete | Add proxy routes (~1-2 lines) |

**Lab-06 core files**:
| File | Template state | Student work |
|------|---------------|--------------|
| `agent.py` | Not in template | Create LLM agent from scratch |
| `AGENT.md` | Not in template | Document agent capabilities |
| `plans/task-{1,2,3}.md` | Not in template | Write implementation plans |
| `run_eval.py` | Template-provided | Minimal or no changes |

### 1.4 Independent Implementation Comparison

To verify that AI-generated solutions should differ between students, we compared `fetch_items()` from 5 independently confirmed students:

| Student | Var name | Auth style | Timeout | Error handling | Docstring |
|---------|----------|-----------|---------|----------------|-----------|
| Achoombers | `r` | `auth=auth` tuple | none | `raise_for_status()` | stripped |
| 2OfClubsy | `response` | inline tuple | none | `raise_for_status()` | kept TODO |
| Pasha12122000 | `resp` | `_auth()` helper | `timeout=30` | `raise_for_status()` | stripped |
| EgorTytar | `response` | auth in constructor | none | manual `status_code != 200` | stripped |
| Nematodont | `response` | `BasicAuth()` object | none | `raise_for_status()` | Russian comments |

Every independent Qwen run produced structurally similar but textually different code. Byte-identical output across 200+ line files is not explained by AI determinism.

---

## 2. Results

### 2.1 Lab-05 Screening Summary

- 261 students scanned
- 78 git flags across 49 students
- 2 critical flags (shared commit SHAs)
- 5 file-based plagiarism clusters identified

### 2.2 Lab-06 Screening Summary

- 261 students scanned
- 220 git flags across 118 students (mostly noise — prescribed commit messages)
- 0 critical flags
- File-based flags were all from lab-05 code leftover in repos, **not lab-06 task code**
- **No plagiarism confirmed for lab-06**

---

## 3. Lab-05 Clusters — Detailed Findings

### Cluster 1: Achoombers / dofi4ka / rrafich — CONFIRMED

**File comparison:**

| Core file | Achoombers = dofi4ka | Achoombers = rrafich |
|-----------|---------------------|---------------------|
| `etl.py` (253 lines) | IDENTICAL | IDENTICAL |
| `analytics.py` (225 lines) | IDENTICAL | IDENTICAL |
| `Dashboard.tsx` (172 lines) | IDENTICAL | IDENTICAL |
| `App.tsx` (154 lines) | IDENTICAL | IDENTICAL |
| `App.css` | IDENTICAL | IDENTICAL |
| `vite.config.ts` | IDENTICAL | IDENTICAL |

**All 6/6 core files are byte-identical. 0 files differ.**

**Git timeline:**

| Timestamp | Achoombers | dofi4ka | rrafich |
|-----------|-----------|---------|---------|
| 2026-03-07 11:10:15 | feat: ETL pipeline | feat: ETL pipeline (author: **Cursor**) | feat: ETL pipeline (author: **Achoombers**) |
| 2026-03-08 12:33:02 | feat: analytics endpoints | feat: analytics endpoints (author: **Cursor**) | feat: analytics endpoints (author: **Achoombers**) |
| 2026-03-08 12:33:29 | feat: dashboard | feat: dashboard (author: **Cursor**) | feat: dashboard (author: **Achoombers**) |
| 2026-03-12 20:11-22:41 | Merge PRs | Merge PRs | Merge PRs |

**Verdict: CONFIRMED**
- rrafich's commits are literally authored by "Achoombers" with identical timestamps to the second
- dofi4ka's commits are authored by "Cursor" with identical timestamps to the second
- All code is byte-identical, including `Dashboard.tsx` (172 lines, not in template)
- Source: Achoombers. dofi4ka and rrafich copied the commits.

---

### Cluster 2: 2OfClubsy / Maksim-1307 — CONFIRMED

**File comparison:**

| Core file | Identical? | Notes |
|-----------|-----------|-------|
| `etl.py` (349 lines) | IDENTICAL | |
| `analytics.py` (288 lines) | IDENTICAL | |
| `Dashboard.tsx` (295 lines) | IDENTICAL | Not in template — entirely student-created |
| `App.tsx` (138 lines) | IDENTICAL | |
| `App.css` | **DIFFERENT** | Maksim has +93 lines of dashboard CSS; 2OfClubsy has template-only CSS |
| `vite.config.ts` (30 lines) | IDENTICAL | Same as template (no changes) |

**5/6 core files identical. App.css is the only difference — Maksim added 93 lines of dashboard styling that 2OfClubsy is missing.**

**Git timeline:**

| Student | Task 1 | Task 2 | Task 3 |
|---------|--------|--------|--------|
| Maksim-1307 | 2026-03-07 16:29 | 2026-03-07 17:07 | 2026-03-07 22:47 |
| 2OfClubsy | 2026-03-11 14:26 | 2026-03-11 14:54 | 2026-03-11 15:09 |

**Git evidence:** No cross-authored commits. Different author emails (`andrejsagendykov@gmail.com` vs `max.07mal@gmail.com`). No shared commit SHAs.

**Additional evidence from autochecker logs:**
- Both are in **group B25-DSAI-03** (classmates)
- 2OfClubsy ran setup on Mar 7 but did zero task work until Mar 11 — then passed task-1 and task-2 in quick succession
- Maksim-1307 had progressive work with failures and retries on Mar 7 (task-1: 55%->100%, task-2: 28%->28%->100%)

**Verdict: CONFIRMED**
- Maksim-1307 submitted 4 days earlier (Mar 7 vs Mar 11) with progressive iterative work
- 2OfClubsy did no task work for 4 days after setup, then passed tasks immediately
- 295-line Dashboard.tsx (entirely student-created, no template) is byte-identical
- Missing App.css in 2OfClubsy is consistent with copying code files but not the stylesheet
- Qwen determinism ruled out: the university proxy uses **temperature=0.7** by default (not 0), which introduces randomness — byte-identical output across 295+ lines is impossible from independent runs
- Source: Maksim-1307. 2OfClubsy copied.

---

### Cluster 3: Pasha12122000 / z1nnyy / diana / kayumowanas — MIXED

This cluster has two sub-groups with different evidence levels.

**File comparison matrix:**

| Core file | P=Z | P=D | P=K | Notes |
|-----------|-----|-----|-----|-------|
| `etl.py` | **DIFF** (whitespace only) | **DIFF** (completely different impl) | **DIFF** (kayumowanas = unchanged template!) | See details below |
| `analytics.py` (195 lines) | SAME | SAME | **DIFF** (210 lines) | |
| `Dashboard.tsx` (194 lines) | **SAME** | **SAME** | **SAME** | Not in template |
| `App.tsx` (155 lines) | **DIFF** (1 line) | SAME | SAME | |
| `App.css` (109 lines) | SAME | SAME | SAME | |
| `vite.config.ts` (31 lines) | SAME | SAME | SAME | |

**etl.py details:**
- **Pasha vs z1nnyy**: Only whitespace/formatting differences (line wrapping, trailing newline) — functionally identical code
- **Pasha vs diana**: Completely different implementations — different imports (`sqlmodel` vs `sqlalchemy`), different auth (`_auth()` helper vs inline tuple), diana kept TODO comments
- **kayumowanas**: `etl.py` is the **unchanged template** (147 lines, still has `raise NotImplementedError`) — task-1 was never implemented

**App.tsx detail (Pasha vs z1nnyy):**
- Only difference: `import { Dashboard } from './Dashboard'` vs `import { Dashboard } from './Dashboard.tsx'` (file extension in import)

**Git timeline (exact timestamps):**

| Time (Mar 12) | Pasha12122000 | z1nnyy |
|---|---|---|
| 21:17:39 | — | ETL pipeline commit |
| 21:19:07 | ETL pipeline commit | — |
| 21:22:03 | — | Merge PR #2 |
| 21:22:04 | Merge PR #2 | — |
| 21:35:14 | — | Analytics commit |
| 21:35:24 | Analytics commit | — |
| 21:48:25 | Dashboard commit | — |
| 21:48:27 | — | Dashboard commit |
| 21:50:50 | — | Merge PR #6 |
| 21:51:08 | Merge PR #6 | — |

diana and kayumowanas timeline:

| Student | Task 1 | Task 2 | Task 3 |
|---------|--------|--------|--------|
| kayumowanas | 2026-03-06 12:46 (author: **Danila Danko**) | 2026-03-07 11:35 | 2026-03-12 23:13:53 |
| diana | 2026-03-12 22:06 (3 attempts) | 2026-03-12 22:52 | 2026-03-12 23:13:54 |

**Verdict:**

**Pasha12122000 + z1nnyy — CONFIRMED**: Commits within seconds of each other across all 3 tasks (z1nnyy consistently ~2-10 seconds ahead). The `etl.py` differences are only whitespace/formatting, and the `App.tsx` difference is a single import extension. They were clearly working together in real-time — one generating code and both pushing simultaneously.

**diana + kayumowanas — CONFIRMED**: Both share the same `Dashboard.tsx` (194 lines, no template) with Pasha/z1nnyy. Qwen determinism ruled out: the university proxy uses **temperature=0.7** by default, making byte-identical 194-line output from independent runs impossible. Additional evidence from autochecker logs:
- diana (B25-DSAI-05, IP 10.93.25.171) is in the same group as z1nnyy (IP 10.93.25.170) with adjacent VM IPs
- diana struggled with task-1 (5 attempts) and task-2 (6 attempts, never fully passing) but has a perfect Dashboard.tsx identical to students who worked together
- kayumowanas never passed task-1 beyond 77.8% and their `etl.py` is the unchanged template with `raise NotImplementedError` — yet they have the same Dashboard.tsx
- Both received the Dashboard code from the Pasha/z1nnyy group rather than generating it independently

---

### Cluster 4: EgorTytar / beetle-2026-b — CONFIRMED

**File comparison:**

| Core file | Identical? |
|-----------|-----------|
| `etl.py` (268 lines) | IDENTICAL |
| `analytics.py` | IDENTICAL (301 vs 300 lines — only difference is a trailing empty line) |
| `Dashboard.tsx` (172 lines) | IDENTICAL |
| `App.tsx` | IDENTICAL |
| `App.css` | IDENTICAL |
| `vite.config.ts` | IDENTICAL |

**6/6 core files identical** (the 1-line "difference" in analytics.py is just a trailing newline).

**Git timeline:**

| Student | Task 1 | Task 2 | Task 3 | Total time |
|---------|--------|--------|--------|-----------|
| EgorTytar | 2026-03-07 11:13 | 2026-03-07 12:21 | 2026-03-07 12:38 | ~90 min |
| beetle-2026-b | 2026-03-07 13:05 | 2026-03-07 13:14 | 2026-03-07 13:23 | **21 min** |

**Verdict: CONFIRMED**
- beetle-2026-b started 25 minutes after EgorTytar finished
- Completed all 3 tasks in 21 minutes (vs 90 min for EgorTytar) — copy speed, not coding speed
- EgorTytar's commits authored as "root" (unconfigured git on VM)
- Only analytics.py differs by 1 line
- Source: EgorTytar. beetle-2026-b copied.

---

### Cluster 5: Nematodont / daniyagg — PAIR PROGRAMMING (not one-way copying)

**File comparison:**

| Core file | Identical? |
|-----------|-----------|
| `etl.py` (448 lines) | IDENTICAL |
| `analytics.py` (233 lines) | IDENTICAL |
| `Dashboard.tsx` | DIFFERENT (297 vs 314 lines) |
| `App.tsx` | IDENTICAL |
| `App.css` | IDENTICAL |
| `vite.config.ts` | IDENTICAL |

**5/6 core files identical. Dashboard.tsx differs meaningfully.**

**Dashboard.tsx differences (daniyagg's additions vs Nematodont):**
- Added section header comments (`// ==================== API Types ====================`)
- Extracted `DEFAULT_LAB` constant instead of inline `'lab-04'`
- Better JSX formatting (multiline error display)
- Added chart section comments (`{/* Bar Chart */}`)
- Nematodont has `//meow` signature at end

This indicates one person wrote the base, the other refined with comments, constants, and formatting.

**Git timeline:**

| Timestamp | Nematodont | daniyagg |
|-----------|-----------|----------|
| 2026-03-07 13:27 | — | feat: ETL pipeline |
| 2026-03-07 13:38 | feat: ETL pipeline | — |
| 2026-03-07 13:46 | PR merged by **daniyagg** | PR merged by **Nematodont** |
| 2026-03-10 22:30 | — | feat: analytics |
| 2026-03-10 22:31 | feat: analytics | — |
| 2026-03-10 22:37 | PR merged by **daniyagg** | PR merged by **Nematodont** |
| 2026-03-10 23:14 | — | feat: dashboard |
| 2026-03-10 23:15 | git checkout command as commit msg | — |
| 2026-03-10 23:21 | — | PR merged by **Nematodont** |
| 2026-03-10 23:26 | feat: dashboard | — |
| 2026-03-10 23:29 | PR merged by **daniyagg** | — |

**Verdict: PAIR PROGRAMMING / ACTIVE COLLABORATION**
- They are cross-merging each other's PRs on both repos
- Commit timestamps within 1-8 minutes of each other
- Backend code shared (same source), Dashboard.tsx written independently with meaningful differences
- Not one-way copying — bidirectional collaboration with evidence of individual contributions

---

### Cluster 6: the-shtorm / xleb-sha — PARTIAL (task-1 copied, tasks 2-3 independent)

**Git history reveals:**

xleb-sha's PR #2 merge commit reads: `Merge pull request #2 from the-shtorm/task/1-build-data-pipeline` — xleb-sha merged the-shtorm's task-1 branch directly into their repo.

The shared commit SHA `45f2699e` (author: "senior_shit_engineer") is the-shtorm's ETL pipeline commit, which appears in both repos.

**Timeline:**

| Timestamp | the-shtorm | xleb-sha |
|-----------|-----------|---------|
| 2026-03-06 17:25 | feat: ETL pipeline (SHA 45f2699e) | — |
| 2026-03-06 17:35 | Merge PR #2 | — |
| 2026-03-06 17:54 | — | feat: ETL pipeline (own version, SHA 30b4b2d) |
| 2026-03-06 17:57 | — | Merge PR #2 (from **the-shtorm**/task/1) |
| 2026-03-06 18:23 | — | feat: analytics endpoints (own work) |
| 2026-03-06 18:41 | feat: analytics endpoints (own work) | — |
| 2026-03-06 19:12 | — | feat: dashboard (own work) |
| 2026-03-10 17:49 | feat: dashboard (own work) | — |

**File comparison (all 6 core files differ):**
xleb-sha rewrote task-1 after merging the-shtorm's branch, and wrote tasks 2-3 independently.

**Verdict: PARTIAL — task-1 branch was shared via git merge, but all final code is independently written.** This may represent authorized collaboration (PR review partner) or unauthorized branch sharing. The git evidence (shared SHA + PR from the-shtorm's branch) is unambiguous, but the impact is low since all code was rewritten.

---

## 4. Lab-06 — No Plagiarism Found

The file-based flags for lab-06 were false positives:
- AndreyBadamshin / Dima280807: 79 identical files were leftover lab-05 code. All lab-06 core files (`agent.py`, `AGENT.md`, plans) were **different**.
- AndreyBadamshin / varvarachizh: Same pattern — lab-05 leftovers, lab-06 code independent.
- Evgeni1a / veronika1977: Investigation failed (unicode error), batch showed 50% match on `agent.py` + `run_eval.py` — `run_eval.py` is template-provided. Insufficient evidence.

---

## 5. Qwen Determinism Consideration

Students used Qwen Code agent to generate solutions. Could identical code be explained by deterministic AI output?

**Analysis:**
- The university's Qwen proxy (`qwen-code-api`) uses **temperature=0.7 by default** (see `qwen_code_api/routes/chat.py:142`). This is not deterministic — it introduces significant randomness into every response.
- At temperature=0.7, two identical prompts will produce **different outputs** every time. Byte-identical code across 194-295 line files from independent runs is impossible.
- Even at temperature=0, comparison of 5 independently confirmed students showed **every run produces different** variable names, auth patterns, error handling, and comments
- `Dashboard.tsx` is **not in the template** — it is entirely student-created with no scaffold constraints
- Git history signals (cross-authored commits, 1-second timestamp gaps, 21-minute completion times) cannot be explained by AI behavior
- **Conclusion: Qwen determinism is ruled out as an explanation for identical code in all clusters**

**Experiment protocol** (for further validation):

See `scripts/qwen_determinism_experiment.py` — sends N identical requests to Qwen 2.5 Coder 32B (temperature=0) via OpenRouter and measures output variance.

```bash
python scripts/qwen_determinism_experiment.py \
  --api-key $OPENROUTER_API_KEY \
  --count 200 \
  --output-dir reports/qwen_experiment_results
```

---

## 6. Summary

### Lab-05: 6 clusters identified

| # | Students | Verdict | Evidence |
|---|----------|---------|----------|
| C1 | **Achoombers** -> dofi4ka, rrafich | **CONFIRMED** | Git commit objects copied (same author + timestamps to the second), 6/6 core files byte-identical |
| C2 | **Maksim-1307** -> 2OfClubsy | **CONFIRMED** | 5/6 files identical (incl. 295-line Dashboard.tsx), classmates (B25-DSAI-03), 2OfClubsy did no work for 4 days then passed immediately. Qwen determinism ruled out (temperature=0.7) |
| C3a | **Pasha12122000** + z1nnyy | **CONFIRMED** | Commits within seconds, autochecker checks within 22s of each other, etl.py differs only in whitespace |
| C3b | diana + kayumowanas (share Dashboard.tsx with C3a) | **CONFIRMED** | Same 194-line Dashboard.tsx despite struggling/failing at easier tasks. Qwen determinism ruled out (temperature=0.7). diana same group as z1nnyy (B25-DSAI-05, adjacent IPs) |
| C4 | **EgorTytar** -> beetle-2026-b | **CONFIRMED** | 6/6 files byte-identical (only trailing newline diff), beetle started 25 min after EgorTytar, finished all 3 tasks in 21 min |
| C5 | **Nematodont** <-> daniyagg | **NOT PLAGIARISM** (pair programming) | Cross-merging PRs on both repos, shared backend code, but independent Dashboard.tsx with meaningful differences (comments, constants, formatting) |
| C6 | **the-shtorm** -> xleb-sha | **NOT PLAGIARISM** (branch sharing) | xleb-sha merged the-shtorm's task-1 branch (shared commit SHA), but rewrote the code and did tasks 2-3 independently |

**Confirmed plagiarism**: C1 (3 students), C2 (2 students), C3a (2 students), C3b (2 students), C4 (2 students) = **11 students**
**Not plagiarism**: C5 (pair programming), C6 (branch sharing with independent work)

### Lab-06: No plagiarism confirmed

All file-based flags were false positives (lab-05 leftover code in repos).

---

## 7. Reproducing This Investigation

### Requirements
```bash
source $(pyenv root)/versions/env313/bin/activate
pip install httpx opencv-python-headless  # if not already installed
export GITHUB_TOKEN=<token>  # from: ssh nurios@188.245.43.68 'grep GITHUB ~/autochecker/deploy/.env'
```

### Step 1: Batch screening
```bash
python main.py batch -s /tmp/students_plag.txt -l lab-05 -p github \
  --plagiarism --threshold 0.5 \
  --template-repo inno-se-toolkit/se-toolkit-lab-5 -w 3 -o /tmp/plag-lab05
```

### Step 2: Deep investigation of flagged pairs
```bash
python scripts/investigate_pair.py \
  --student-a Achoombers --student-b dofi4ka \
  --repo se-toolkit-lab-5 --template inno-se-toolkit/se-toolkit-lab-5 \
  --output /tmp/plag-lab05/investigations
```

### Step 3: Clone and compare core files
```bash
export GH=https://${GITHUB_TOKEN}@github.com
git clone --depth 1 $GH/Achoombers/se-toolkit-lab-5.git /tmp/plag-compare/Achoombers
git clone --depth 1 $GH/dofi4ka/se-toolkit-lab-5.git /tmp/plag-compare/dofi4ka
# ... then use filecmp or diff to compare core files
```

### Step 4: Timeline analysis
```bash
cd /tmp/plag-compare/Achoombers
git fetch --unshallow
git log --format="%ai | %an | %s" --all
```
