# Plagiarism Investigation Report: Lab 05 & Lab 06

**Date**: 2026-03-29
**Investigator**: Automated screening + manual review

---

## 1. Methodology

The investigation followed a multi-layered approach, each layer adding evidence beyond what the previous one provided.

### 1.1 Automated Screening (file hashing + git history)

Batch plagiarism check was run on 261 students for both labs. The tool hashes every source file (excluding files identical to the template repo), then flags pairs of students whose repos share files above a similarity threshold. Separately, it scans git history for shared commit SHAs, identical commit messages, and cross-author emails.

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

# Run for each lab
python main.py batch \
  -s /tmp/students_plag.txt -l lab-05 -p github \
  --plagiarism --threshold 0.5 \
  --template-repo inno-se-toolkit/se-toolkit-lab-5 \
  -w 3 -o /tmp/plag-lab05
```

### 1.2 Deep Pair Investigation (git clone + diff)

Flagged pairs were investigated by cloning both repos and running a detailed comparison: file categorization (identical to template / identical modified / different / only in A / only in B), git timeline reconstruction, and cross-author analysis.

```bash
python scripts/investigate_pair.py \
  --student-a <name> --student-b <name> \
  --repo se-toolkit-lab-5 \
  --template inno-se-toolkit/se-toolkit-lab-5 \
  --output /tmp/plag-lab05/investigations
```

### 1.3 Template Scaffold Analysis

The upstream template was analyzed to distinguish scaffolding (AI-generated `.claude/skills/`, config files) from core task files that students must write independently. Only core files were considered for plagiarism verdicts.

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

### 1.4 Core File Comparison (byte-level diff)

For each cluster, all 6 core files were compared byte-for-byte using `diff`. When files differed, the actual differences were examined (whitespace-only? trailing newline? completely different implementation?).

### 1.5 Git Timeline Analysis

Full commit history (after `git fetch --unshallow`) was examined for:
- **Commit timestamps**: Who committed first? How far apart? Suspiciously synchronized?
- **Commit authors**: Does student A's repo contain commits authored by student B?
- **Branch names in merge commits**: Did anyone merge another student's branch directly?

### 1.6 PR Review Analysis

GitHub PR reviews were checked via `gh api repos/<user>/se-toolkit-lab-5/pulls/<n>/reviews`. The lab requires at least 1 PR approval per task. Review pairs reveal:
- Who reviewed whose code (and therefore saw it)
- Whether the source student approved the copy (implying awareness)

### 1.7 Autochecker Bot Logs

The bot database (`bot.db`) was queried for:
- **Student profiles**: group, VM IP, registration date
- **Check results**: score progression over time (did they iterate and debug, or pass immediately?)
- **Attempt timestamps**: synchronized checking patterns between students

### 1.8 AI Determinism Analysis

Students used Qwen Code agent via the university's `qwen-code-api` proxy. We investigated whether identical code could result from deterministic AI output:
- **Proxy default temperature**: `0.7` (source: `qwen_code_api/routes/chat.py:142`). At this temperature, LLM output is non-deterministic — identical prompts produce different outputs every run. Byte-identical code across 194-295 lines is impossible from independent runs.
- **Independent implementation comparison**: `fetch_items()` was compared across 5 independently confirmed students — every run produced different variable names, auth patterns, error handling, and docstrings.
- **Conclusion**: Qwen determinism is ruled out as an explanation for byte-identical code.

### 1.9 Prescribed vs. Suspicious Signals

The lab spec prescribes specific commit messages (e.g., `feat: implement ETL pipeline for autochecker data`), so identical commit messages are **not** evidence of plagiarism. Similarly, `.claude/skills/` directories and AI scaffolding files are expected to be similar across students using the same tools.

---

## 2. Screening Results

### 2.1 Lab-05

- 261 students scanned (252 successful, 9 repo errors)
- 78 git flags across 49 students
- 2 critical flags (shared commit SHAs)
- 14 students flagged for file-based similarity
- 6 clusters identified after investigation

### 2.2 Lab-06

- 261 students scanned (250 successful, 11 repo errors)
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

**PR reviews:** None of the three had any PR reviews — they skipped the review process entirely.

**Awareness analysis:**
- Achoombers's own commits are authored "Achoombers" `<o.grekhov@innopolis.university>`
- rrafich's copies have author "Achoombers" — matches Achoombers's repo exactly, consistent with direct copy from the public repo (rrafich could have done this without Achoombers knowing)
- dofi4ka's copies have author "Cursor" (the AI IDE) — a different author, suggesting the code traveled through a different path (possibly generated on a machine with Cursor as git author, or dofi4ka re-committed via Cursor)
- No PR reviews — no review-based evidence of mutual awareness
- Achoombers could be unaware of the copying (public repo), but cannot be confirmed either way

**Verdict: CONFIRMED** — Git commit objects were copied with identical timestamps to the second. All code is byte-identical, including `Dashboard.tsx` (172 lines, not in template). Source: Achoombers.

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

**5/6 core files identical.** App.css is the only difference — Maksim added 93 lines of dashboard styling that 2OfClubsy is missing.

**Git timeline:**

| Student | Task 1 | Task 2 | Task 3 |
|---------|--------|--------|--------|
| Maksim-1307 | 2026-03-07 16:29 | 2026-03-07 17:07 | 2026-03-07 22:47 |
| 2OfClubsy | 2026-03-11 14:26 | 2026-03-11 14:54 | 2026-03-11 15:09 |

No cross-authored commits. Different author emails. No shared commit SHAs.

**Autochecker logs:**
- Both in **group B25-DSAI-03** (classmates)
- Maksim-1307 had progressive work with failures and retries (task-1: 55%->100%, task-2: 28%->28%->100%)
- 2OfClubsy ran setup on Mar 7 but did zero task work until Mar 11 — then passed task-1 and task-2 in quick succession

**PR reviews:** Maksim-1307 **approved all 3 of 2OfClubsy's PRs** (containing code byte-identical to Maksim's own). Maksim's own PRs were reviewed by TeraloToxin (unrelated student).

**Awareness analysis:** Maksim reviewed and approved his own code in 2OfClubsy's repo — **Maksim was aware of the copying**. Both are accountable.

**Verdict: CONFIRMED** — 295-line Dashboard.tsx (no template) byte-identical. 4-day gap. 2OfClubsy did no work then passed immediately. Qwen determinism ruled out (temperature=0.7). Source: Maksim-1307. Both aware (PR reviews).

---

### Cluster 3: Pasha12122000 / z1nnyy / diana / kayumowanas — CONFIRMED

This cluster has two sub-groups.

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
- **Pasha vs diana**: Completely different implementations — different imports (`sqlmodel` vs `sqlalchemy`), different auth pattern (`_auth()` helper vs inline tuple), diana kept TODO comments
- **kayumowanas**: `etl.py` is the **unchanged template** (147 lines, still has `raise NotImplementedError`) — task-1 was never implemented

**App.tsx detail (Pasha vs z1nnyy):**
- Only difference: `import { Dashboard } from './Dashboard'` vs `import { Dashboard } from './Dashboard.tsx'` (file extension in import)

#### Sub-group C3a: Pasha12122000 + z1nnyy — CONFIRMED

**Git timeline (exact timestamps, Mar 12):**

| Time | Pasha12122000 | z1nnyy |
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

**Autochecker logs:** z1nnyy and Pasha ran setup within 22 seconds of each other (18:01:58 vs 18:02:20), then checked tasks in lockstep.

**PR reviews:** Pasha <-> z1nnyy cross-reviewed all PRs — mutual collaboration.

**Awareness:** Both fully aware — active real-time collaboration with commits within seconds.

**Verdict: CONFIRMED** — Commits within seconds across all 3 tasks. etl.py differs only in whitespace, App.tsx by 1 character. Both working together in real-time.

#### Sub-group C3b: diana + kayumowanas — CONFIRMED

**Git timeline:**

| Student | Group | Task 1 | Task 2 | Task 3 |
|---------|-------|--------|--------|--------|
| kayumowanas | B25-CSE-04 | 2026-03-06 12:46 (author: **Danila Danko**) | 2026-03-07 11:35 | 2026-03-12 23:13:53 |
| diana | B25-DSAI-05 | 2026-03-12 22:06 (3 failed attempts) | 2026-03-12 22:52 | 2026-03-12 23:13:54 |

**Autochecker logs:**
- diana struggled with task-1 (5 attempts, max 66.7% until attempt 5) and task-2 (6 attempts, never fully passing)
- kayumowanas never passed task-1 beyond 77.8%; their `etl.py` is the unchanged template with `raise NotImplementedError`
- diana (B25-DSAI-05, IP 10.93.25.171) is in the same group as z1nnyy (IP 10.93.25.170) with adjacent VM IPs

**PR reviews:** diana <-> kayumowanas cross-reviewed all PRs — they are each other's review partners.

**Awareness:** Both aware via mutual PR reviews. diana likely received the Dashboard from z1nnyy (same group, adjacent IPs).

**Verdict: CONFIRMED** — Both share the same 194-line Dashboard.tsx (no template) with Pasha/z1nnyy, despite struggling or failing at easier tasks. Qwen determinism ruled out (temperature=0.7). kayumowanas has an unimplemented etl.py but a perfect Dashboard — received code, didn't write it.

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

**PR reviews:** EgorTytar **approved all 3 of beetle-2026-b's PRs** (containing his own identical code). beetle-2026-b approved all 3 of EgorTytar's PRs.

**Awareness:** EgorTytar reviewed and approved his own code in beetle's repo — **both were aware**.

**Verdict: CONFIRMED** — 6/6 files byte-identical. beetle started 25 min after EgorTytar finished and completed all 3 tasks in 21 minutes (copy speed). EgorTytar's commits authored as "root" (unconfigured git). Both aware via mutual PR reviews.

---

### Cluster 5: Nematodont / daniyagg / mccmmc — CONFIRMED

**File comparison (3-way):**

| Core file | N=D | N=M | D=M |
|-----------|-----|-----|-----|
| `etl.py` | **SAME** (448 lines) | DIFF (448 vs 316) | DIFF |
| `analytics.py` (233 lines) | **SAME** | **SAME** | **SAME** |
| `Dashboard.tsx` | DIFF (298 vs 315) | DIFF (1 line: `//meow`) | DIFF (22 lines) |
| `App.tsx` (158 lines) | **SAME** | **SAME** | **SAME** |
| `App.css` (61 lines) | **SAME** | **SAME** | **SAME** |
| `vite.config.ts` (30 lines) | **SAME** | **SAME** | **SAME** |

**Dashboard.tsx analysis:**
- **Nematodont vs mccmmc**: differ by exactly 1 line — `//meow` (Nematodont's signature). mccmmc has Nematodont's code without the signature.
- **daniyagg vs Nematodont**: daniyagg added section header comments, extracted `DEFAULT_LAB` constant, improved formatting — cosmetic changes only, not independent work.
- **etl.py**: Nematodont=daniyagg (identical 448 lines). mccmmc has a different version (316 lines, different imports, no Russian comments) — the only file where mccmmc shows independent work.

**Pattern**: Nematodont wrote the code, distributed to daniyagg and mccmmc. daniyagg made cosmetic edits to Dashboard. mccmmc wrote own etl.py but copied everything else.

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

**PR reviews:** 3-person ring — Nematodont <-> daniyagg cross-reviewed, mccmmc ("Potushinskii Maxim") approved Nematodont's task-1 PR.

**Cross-lab confirmation:** In lab-07, all three have **12/12 files 100% identical**, forming the same 3-person review ring. The lab-07 evidence removes any doubt about lab-05.

**Verdict: CONFIRMED** — Nematodont is the source. daniyagg and mccmmc received code with at most cosmetic changes. The 3-person ring is consistent across labs 05 and 07.

---

### Cluster 6: the-shtorm / xleb-sha — NOT PLAGIARISM (branch sharing, independent work)

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

**File comparison:** All 6 core files differ — xleb-sha rewrote task-1 after merging the-shtorm's branch, and wrote tasks 2-3 independently.

**Verdict: NOT PLAGIARISM** — Task-1 branch was shared via git merge (shared SHA proves it), but all final code is independently written. May represent authorized collaboration (PR review partner) or unauthorized branch sharing, but impact is zero since all code was rewritten.

---

## 4. Lab-07 Clusters — Detailed Findings

Batch screening: 261 students, 251 successful, 172 git flags (0 critical), 2 file-based clusters.

Both clusters are repeat offenders from lab-05.

### Lab-07 Cluster A: EgorTytar / beetle-2026-b — CONFIRMED (repeat of lab-05 C4)

**Identical files (5/7 bot files):** `lms_client.py`, `basic.py`, `bot.py`, `llm_client.py`, `router.py`

**Git timeline:**

| Student | Task 1 | Task 2 | Task 3 | Task 4 |
|---------|--------|--------|--------|--------|
| EgorTytar | 2026-03-20 19:26 | 2026-03-20 19:47 | 2026-03-20 21:46 | 2026-03-20 22:56 |
| beetle-2026-b | 2026-03-23 15:46 | 2026-03-23 17:05 | 2026-03-23 18:01 | 2026-03-23 18:15 |

EgorTytar first (Mar 20), beetle-2026-b 3 days later (Mar 23). Same pattern as lab-05.

**PR reviews:** EgorTytar <-> beetle-2026-b cross-reviewed all PRs. Both aware.

**Verdict: CONFIRMED** — Same pair, same pattern as lab-05 C4.

### Lab-07 Cluster B: Nematodont / daniyagg / mccmmc — CONFIRMED (repeat of lab-05 C5)

**12/12 bot files 100% identical** across all 3 students: `scores.py`, `lms_client.py`, `__init__.py` (services), `health.py`, `__init__.py` (handlers), `labs.py`, `bot.py`, `llm_client.py`, `intent.py`, `start.py`, `help.py`, `config.py`

**Git timeline:**

| Student | Task 1 | Task 2 | Task 3 | Task 4 |
|---------|--------|--------|--------|--------|
| Nematodont | 2026-03-23 11:54 | 2026-03-26 12:18 | 2026-03-26 19:35 | 2026-03-26 20:23 |
| daniyagg | 2026-03-23 11:54 | 2026-03-26 12:20 | 2026-03-26 19:42 | 2026-03-26 20:23 |
| mccmmc | 2026-03-23 21:38 | 2026-03-23 22:43 (multiple fixes through Mar 24) | 2026-03-26 19:00 | 2026-03-26 19:57 |

**PR reviews:** 3-person ring — Nematodont merges mccmmc's PRs, mccmmc merges daniyagg's PRs, daniyagg merges Nematodont's PRs.

**Verdict: CONFIRMED** — 100% identical code across all 3. Same trio as lab-05 C5, now with zero differences.

---

## 5. Lab-06 — No Plagiarism Found

The file-based flags for lab-06 were false positives:
- AndreyBadamshin / Dima280807: 79 identical files were leftover lab-05 code. All lab-06 core files (`agent.py`, `AGENT.md`, plans) were **different**.
- AndreyBadamshin / varvarachizh: Same pattern — lab-05 leftovers, lab-06 code independent.
- Evgeni1a / veronika1977: Investigation failed (unicode error), batch showed 50% match on `agent.py` + `run_eval.py` — `run_eval.py` is template-provided. Insufficient evidence.

---

## 5. Summary

### Lab-05: 6 clusters identified

| # | Students | Verdict | Key evidence |
|---|----------|---------|----------|
| C1 | **Achoombers** -> dofi4ka, rrafich | **CONFIRMED** | Git commit objects copied (same author + timestamps to the second), 6/6 core files byte-identical. No PR reviews. |
| C2 | **Maksim-1307** <-> 2OfClubsy | **CONFIRMED** | 5/6 identical (incl. 295-line Dashboard.tsx), classmates, 4-day gap, Maksim approved 2OfClubsy's copied PRs. Both aware. |
| C3a | **Pasha12122000** <-> z1nnyy | **CONFIRMED** | Commits within seconds, autochecker checks within 22s, cross-reviewed PRs. Both aware. |
| C3b | diana + kayumowanas | **CONFIRMED** | Same 194-line Dashboard.tsx as C3a despite failing easier tasks. Cross-reviewed PRs. diana same group/adjacent IP as z1nnyy. |
| C4 | **EgorTytar** <-> beetle-2026-b | **CONFIRMED** | 6/6 identical, beetle finished in 21 min, EgorTytar approved beetle's copied PRs. Both aware. |
| C5 | **Nematodont** -> daniyagg, mccmmc | **CONFIRMED** | Nematodont is source (`//meow` signature). mccmmc has code minus signature. daniyagg added cosmetic comments only. 3-person ring confirmed by lab-07 (12/12 files 100% identical). |
| C6 | **the-shtorm** -> xleb-sha | **NOT PLAGIARISM** | Branch shared via git merge, but all final code independently rewritten. |

**Confirmed plagiarism**: C1 (3), C2 (2), C3a (2), C3b (2), C4 (2), C5 (3) = **14 students**
**Not plagiarism**: C6 (branch sharing with independent work)

### Lab-06: No plagiarism confirmed

All file-based flags were false positives (lab-05 leftover code in repos).

### Lab-07: 2 clusters (repeat offenders)

| # | Students | Verdict | Key evidence |
|---|----------|---------|----------|
| A | **EgorTytar** <-> beetle-2026-b | **CONFIRMED** | 5/7 bot files identical. Same pair as lab-05 C4, same pattern. |
| B | **Nematodont** -> daniyagg, mccmmc | **CONFIRMED** | 12/12 files 100% identical. Same trio as lab-05 C5, 3-person review ring. |

**Confirmed plagiarism**: A (2), B (3) = **5 students** (all repeat offenders from lab-05)

---

## 6. Reproducing This Investigation

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
# then: diff Achoombers/backend/app/etl.py dofi4ka/backend/app/etl.py
```

### Step 4: Timeline analysis
```bash
cd /tmp/plag-compare/Achoombers
git fetch --unshallow
git log --format="%ai | %an <%ae> | %s" --all
```

### Step 5: PR review analysis
```bash
gh api repos/Achoombers/se-toolkit-lab-5/pulls?state=all --jq '.[].number' | while read pr; do
  gh api repos/Achoombers/se-toolkit-lab-5/pulls/$pr/reviews \
    --jq '.[] | "PR#'$pr' reviewed by \(.user.login) (\(.state))"'
done
```

### Step 6: Autochecker bot logs
```bash
ssh nurios@188.245.43.68 "docker exec autochecker-bot python3 -c \"
import sqlite3
conn = sqlite3.connect('/app/data/bot.db')
# Query users, results, attempts tables by tg_id
\""
```
