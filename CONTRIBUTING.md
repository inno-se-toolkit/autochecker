# Keeping Autochecker Specs in Sync with Labs

This document explains how to maintain autochecker spec files when lab instructions change.

## When to update the spec

Update the spec whenever the lab README or task files change:

- Task added, removed, or renumbered
- Section headings renamed in task instructions
- Issue titles changed
- File paths changed (e.g. `docs/skill-development-plan.md`)
- Acceptance criteria added, removed, or modified
- Minimum counts changed (e.g. "at least 5 components")

## Spec structure

Each lab has a YAML spec file in `specs/` (e.g. `specs/lab-01.yaml`). The spec contains:

```yaml
id: lab-01
title: "Lab 01 – ..."
repo_name: "lab-01-market-product-and-git"

tasks:                      # Task metadata (used by the Telegram bot)
  - id: setup
    title: "Lab setup"
  - id: task-1
    title: "Task 1: Product & architecture description"

checks:                     # Individual checks, grouped by task
  - id: t1_arch_md_exists
    task: task-1            # Links check to a task group
    type: file_exists
    description: "docs/architecture.md exists"
    hint: >                 # Student-facing message shown on failure
      Create the file docs/architecture.md in your repo.
    params:
      path: "docs/architecture.md"
```

### Key fields

| Field | Purpose |
|-------|---------|
| `task` | Groups check under a task (used for `--task` filtering and bot) |
| `hint` | Student-facing failure message (shown in student_report.txt and bot) |
| `description` | Human-readable check title |
| `type` | Check type (see available types below) |
| `params` | Type-specific parameters |
| `is_required` | Whether check counts toward the required score (default: true) |

### Available check types

| Type | What it checks | Key params |
|------|---------------|------------|
| `repo_exists` | Repository is accessible | — |
| `repo_is_fork` | Repo is a fork | — |
| `repo_has_issues` | Issues are enabled | — |
| `file_exists` | File exists in repo | `path` |
| `glob_exists` | Files matching glob pattern exist | `pattern` |
| `issue_exists` | Issue with matching title exists | `pattern` (regex) |
| `issues_count` | Minimum number of matching issues | `pattern`, `min_count` |
| `regex_in_file` | Regex match in a file | `path`, `pattern`, `min_matches` |
| `markdown_sections_nonempty` | Markdown has non-empty sections | `path`, `headings` |
| `markdown_regex_all` | All regex patterns found in markdown | `path`, `patterns` |
| `markdown_linked_files_exist` | Referenced files exist | `path`, `pattern` |
| `markdown_section_item_count` | Section has min number of list items | `path`, `heading`, `min_items` |
| `urls_in_markdown_section_min` | Section has min number of URLs | `path`, `heading`, `min_urls` |
| `pr_merged_count` | Minimum merged PRs | `min_count` |
| `pr_body_regex_count` | PRs matching body regex | `pattern`, `min_count` |
| `pr_review_approvals` | PR review approvals exist | `min_count` |
| `pr_review_line_comments` | PR line comments exist | `min_count` |
| `commit_message_regex` | Commit messages match pattern | `pattern`, `min_ratio` |
| `llm_judge` | LLM-based content quality check | `path`, `rubric`, `min_score` |

## How to update a spec

1. Read the latest task file (e.g. `lab/tasks/required/task-1.md` in the lab repo)
2. Compare acceptance criteria with spec checks
3. For each acceptance criterion, verify a corresponding check exists
4. Update headings, regex patterns, file paths, counts to match
5. Update `hint` messages to reference correct step numbers

## Checklist for each task

For each required/optional task, verify:

- [ ] `tasks:` metadata entry exists with correct `id` and `title`
- [ ] Issue title regex matches the exact title in the task file
- [ ] File paths match (e.g. `docs/architecture.md`, `CONTRIBUTORS.md`)
- [ ] Markdown section headings match exactly (case-sensitive)
- [ ] Min counts match (e.g. >=5 components, >=2 assumptions)
- [ ] LLM rubric reflects current acceptance criteria
- [ ] `hint` message is actionable and references correct instructions
- [ ] Check IDs follow the naming convention: `t{N}_{descriptive_name}`

## For AI agents

When asked to update a spec:

1. Fetch the latest lab files from the lab repo (use `git show origin/main:<path>` or read files directly)
2. Read each task file under `lab/tasks/required/` and `lab/tasks/optional/`
3. Compare acceptance criteria line-by-line with existing spec checks
4. Identify mismatches: renamed sections, changed titles, new/removed checks
5. Update the YAML spec accordingly
6. Verify by running:
   ```bash
   python main.py check -s <student> -l <lab> -t <task> -p github
   ```

### Common pitfalls

- Section headings are **case-sensitive** — "Product Choice" != "Product choice"
- Issue title regexes use `(?i)` for case-insensitive matching but the base text must be exact
- `glob_exists` patterns must use the repo's actual directory structure
- LLM rubrics should be updated when acceptance criteria change significantly
- The `tasks:` metadata list determines what appears in the Telegram bot — keep it in sync

## Testing changes

```bash
# Test a specific task
python main.py check -s <student> -l lab-01 -t task-0 -p github

# Test all checks
python main.py check -s <student> -l lab-01 -p github

# Batch check all students
python main.py batch -l lab-01 -p github
```
