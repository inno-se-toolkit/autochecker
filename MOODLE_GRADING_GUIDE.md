# Moodle → Autochecker → Grades: End-to-End Guide

How to take Moodle submissions, run autochecker, and produce a CSV ready to upload back to Moodle.

## Overview

Three data sources need to be joined:

| Source | What it has | Key field |
|---|---|---|
| **Moodle Grades CSV** | First name, Last name, Email | Full name |
| **Moodle Submissions folder** | `onlinetext.html` with GitHub URL/username | Full name (folder prefix) |
| **Autochecker results** | `results.jsonl` with score + per-check details | GitHub username (folder name) |

The join chain: **Grades CSV** ←(full name)→ **Submissions** ←(GitHub username)→ **Results**

## Step-by-Step

### 1. Export from Moodle

Download two things from the Moodle assignment page:

**a) Grades CSV** — go to the course gradebook or assignment grading page and export as CSV.
Expected columns: `First name, Last name, ID number, Institution, Department, Email address, ...`

**b) Submissions** — "Download all submissions" from the assignment.
This creates a folder like `[S26]SofEngToo-Lab submission-145430 (1)/` containing:
```
Abdugaffar Sapayev_513256_assignsubmission_onlinetext/
  onlinetext.html      ← contains the GitHub URL the student submitted
Adeliia Verenikina_513275_assignsubmission_onlinetext/
  onlinetext.html
...
```

### 2. Extract GitHub usernames from submissions

Each `onlinetext.html` contains the student's submitted text — typically a GitHub repo URL like:
```html
<p>https://github.com/USERNAME/lab-01-market-product-and-git</p>
```

The GitHub username is extracted from the URL path. Watch out for:
- **Bare usernames** — some students submit just `USERNAME` without a full URL
- **Extra paths** — some submit `github.com/USERNAME/repo/issues` or `/tree/main`
- **Trailing garbage** — tabs, query params, etc.

### 3. Run autochecker batch

Create a `students.csv` with one GitHub username per line:
```csv
student_alias
Jack488-code
Adeliver
adelinamikki
```

Then run:
```bash
source $(pyenv root)/versions/env313/bin/activate
cd /path/to/autochecker

python3 main.py batch \
  -s students.csv \
  -l lab-01 \
  -p github \
  --workers 2 \
  --plagiarism
```

This creates `results/{username}/results.jsonl` and `results/{username}/summary.html` for each student.

### 4. Join into final grades CSV

Run the join script (see `scripts/moodle_join.py` or do it manually):

```
Grades CSV (email)  ←→  Submissions (name→github)  ←→  Results (github→score)
```

Output: `lab01-final-grades.csv` with columns `Email, Full Name, Grade, Feedback`

### 5. Upload back to Moodle

Import the CSV into the Moodle gradebook. The `Email` column is the stable identifier.

---

## Gotchas & Lessons Learned

### Unicode normalization (critical!)
Moodle folder names and the grades CSV may encode the same character differently.
Example: Cyrillic `й` can be either:
- **Precomposed (NFC):** `\xd0\xb9` — one codepoint
- **Decomposed (NFD):** `\xd0\xb8\xcc\x86` — `и` + combining breve

**Always normalize with `unicodedata.normalize("NFC", name)` before comparing.**

### Submission URL parsing
Students submit all kinds of things:
- Full repo URL: `https://github.com/user/repo` (most common)
- Repo subpage: `https://github.com/user/repo/issues` or `/tree/main`
- Bare username: `kris537`
- URL with query params: `github.com/user/repo?tab=repositories`

Use a regex like `github\.com/([^/\s"<>]+)` for URLs, with a fallback for bare `<p>username</p>`.

### Results without `results.jsonl`
When a repo is not found or is private, the autochecker only writes `summary.html` (a short failure message), not `results.jsonl`. These students get grade 0 — extract the failure reason from the HTML.

### Students with no submission
Students in the grades CSV who have no submission folder should get grade 0 and feedback "No submission".

### Name matching between Grades CSV and Submissions
- Grades CSV has separate `First name` / `Last name` columns
- Submission folders use `"FirstName LastName_ID_assignsubmission_onlinetext"`
- Join on `f"{first} {last}"` after NFC normalization
- Mixed-script names exist (e.g., Cyrillic first name + Latin last name: `Савелий Gusev`)

### Grade format
- Autochecker outputs percentage like `56.52%`
- Moodle expects a number (points out of 100)
- Round: `round(float(score.rstrip('%')))`

### Feedback format
- `summary.html` is HTML — Moodle's "Feedback comments" column accepts HTML
- If uploading to a system that doesn't render HTML, convert to plain text using `results.jsonl` directly (list failed checks with descriptions)

---

## Quick Reference: File Locations

```
# Moodle exports (in ~/Downloads after export)
~/Downloads/[S26]SofEngToo Grades-*.csv              # grades + emails
~/Downloads/[S26]SofEngToo-Lab submission-*/          # submission folders

# Autochecker
autochecker/main.py                                   # CLI entry point
autochecker/specs/lab-01.yaml                         # lab spec
autochecker/results/{github_username}/results.jsonl   # per-student results
autochecker/results/{github_username}/summary.html    # per-student HTML report
autochecker/results/batch_summary.html                # batch overview
autochecker/students.csv                              # input for batch command

# Output
~/Downloads/lab01-final-grades.csv                    # final CSV for upload
```

## Environment Setup

```bash
# Activate the Python environment
source $(pyenv root)/versions/env313/bin/activate

# Required env vars (in autochecker/.env)
GITHUB_TOKEN=ghp_...          # GitHub PAT for API access
OPENROUTER_API_KEY=sk-or-...  # for LLM checks (optional but recommended)
LLM_MODEL=google/gemini-2.5-flash-lite
```
