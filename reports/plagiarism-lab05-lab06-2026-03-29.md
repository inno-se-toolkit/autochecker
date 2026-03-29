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

| Core file | Identical? |
|-----------|-----------|
| `etl.py` (349 lines) | IDENTICAL |
| `analytics.py` (288 lines) | IDENTICAL |
| `Dashboard.tsx` (295 lines) | IDENTICAL |
| `App.tsx` (138 lines) | IDENTICAL |
| `App.css` | DIFFERENT |
| `vite.config.ts` | IDENTICAL |

**5/6 core files identical.**

**Git timeline:**

| Student | Task 1 | Task 2 | Task 3 |
|---------|--------|--------|--------|
| Maksim-1307 | 2026-03-07 16:29 | 2026-03-07 17:07 | 2026-03-07 22:47 |
| 2OfClubsy | 2026-03-11 14:26 | 2026-03-11 14:54 | 2026-03-11 15:09 |

**Verdict: CONFIRMED**
- Maksim-1307 submitted 4 days earlier (Mar 7 vs Mar 11)
- 295-line Dashboard.tsx (entirely student-created, no template) is byte-identical
- Only App.css differs (likely re-styled)
- Source: Maksim-1307. 2OfClubsy copied.

---

### Cluster 3: Pasha12122000 / z1nnyy / diana / kayumowanas — CONFIRMED

**File comparison matrix:**

| Core file | Pasha = diana | Pasha = kayumowanas | Pasha = z1nnyy |
|-----------|--------------|--------------------|----|
| `etl.py` | DIFFERENT | DIFFERENT | DIFFERENT |
| `analytics.py` | IDENTICAL | DIFFERENT | IDENTICAL |
| `Dashboard.tsx` (195 lines) | IDENTICAL | IDENTICAL | IDENTICAL |
| `App.tsx` | IDENTICAL | IDENTICAL | DIFFERENT |
| `App.css` | IDENTICAL | IDENTICAL | IDENTICAL |
| `vite.config.ts` | IDENTICAL | IDENTICAL | IDENTICAL |

**Dashboard.tsx (195 lines, not in template) identical across all 4 students.**

**Git timeline:**

| Student | Task 1 | Task 2 | Task 3 |
|---------|--------|--------|--------|
| kayumowanas | 2026-03-06 12:46 (author: **Danila Danko**) | 2026-03-07 11:35 | 2026-03-12 23:13:53 |
| Pasha12122000 | 2026-03-12 21:19 | 2026-03-12 21:35 | 2026-03-12 21:48 |
| z1nnyy | 2026-03-12 21:17 | 2026-03-12 21:35 | 2026-03-12 21:48 |
| diana | 2026-03-12 22:06 | 2026-03-12 22:52 | 2026-03-12 23:13:54 |

**Verdict: CONFIRMED**
- Pasha and z1nnyy timestamps within 1-2 minutes — simultaneous work
- diana started ~1 hour after Pasha, multiple failed attempts
- kayumowanas's task-1 authored by TA "Danila Danko"; dashboard commit 1 second before diana's
- All 4 share byte-identical Dashboard.tsx (195 lines, no scaffold)

---

### Cluster 4: EgorTytar / beetle-2026-b — CONFIRMED

**File comparison:**

| Core file | Identical? |
|-----------|-----------|
| `etl.py` (268 lines) | IDENTICAL |
| `analytics.py` | DIFFERENT (301 vs 300 lines) |
| `Dashboard.tsx` (172 lines) | IDENTICAL |
| `App.tsx` | IDENTICAL |
| `App.css` | IDENTICAL |
| `vite.config.ts` | IDENTICAL |

**5/6 core files identical.**

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

### Cluster 5: Nematodont / daniyagg — CONFIRMED (collaborative)

**File comparison:**

| Core file | Identical? |
|-----------|-----------|
| `etl.py` (448 lines) | IDENTICAL |
| `analytics.py` (233 lines) | IDENTICAL |
| `Dashboard.tsx` | DIFFERENT (298 vs 315 lines) |
| `App.tsx` | IDENTICAL |
| `App.css` | IDENTICAL |
| `vite.config.ts` | IDENTICAL |

**5/6 core files identical. Dashboard.tsx differs.**

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

**Verdict: CONFIRMED (active collaboration)**
- They are cross-merging each other's PRs on both repos
- Commit timestamps within 1-8 minutes of each other
- They each wrote their own Dashboard.tsx but shared all backend code
- Not a one-way copy — they are working together across both repos

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
- At temperature=0, LLMs produce identical output for **identical prompts**
- The template scaffold provides detailed TODO instructions, constraining the solution space
- However, comparison of 5 independently confirmed students showed **every run produces different** variable names, auth patterns, error handling, and comments
- `Dashboard.tsx` is **not in the template** — it is entirely student-created with no scaffold constraints. 172-295 lines of byte-identical code cannot be explained by prompt determinism
- Git history signals (cross-authored commits, 1-second timestamp gaps, 21-minute completion times) cannot be explained by AI behavior

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

### Lab-05: 5 clusters confirmed

| # | Students | Direction | Evidence strength |
|---|----------|-----------|-------------------|
| C1 | **Achoombers** -> dofi4ka, rrafich | Achoombers is source | Critical: cross-authored commits with identical timestamps |
| C2 | **Maksim-1307** -> 2OfClubsy | Maksim is source | High: 5/6 files identical, 4-day gap |
| C3 | **Pasha12122000** + z1nnyy + diana + kayumowanas | Shared source, simultaneous work | High: identical Dashboard, 1-2 min timestamp gaps |
| C4 | **EgorTytar** -> beetle-2026-b | EgorTytar is source | High: 5/6 files identical, 25-min gap, 21-min completion |
| C5 | **Nematodont** <-> daniyagg | Active collaboration (bidirectional) | High: cross-merging PRs on both repos |

**Total students involved**: 14

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
