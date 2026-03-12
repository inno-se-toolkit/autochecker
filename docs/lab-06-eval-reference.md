# Lab 06 — Evaluation Reference

How each question is verified, what the student sees locally vs what the bot checks.

## Architecture

```
Student local (run_eval.py)          Autochecker bot (clone_and_run)
─────────────────────────────        ──────────────────────────────────
Fetches Q from dashboard API         Reads lab-06-eval.yaml directly
  → only non-bot_only (0-9)            → all 20 questions (0-19)
Runs agent.py locally                Clones repo, starts Docker Compose
  → student's OpenRouter key            → injected Groq creds
Checks: keywords + source + tools    Checks: keywords OR LLM judge + source + tools
No rubric judging (keyword only)     Rubric → LLM judge (score ≥3/5), keyword fallback
```

## Three-layer verification

Every question is checked in order. All three must pass.

1. **Answer match** — keyword matching (`contains_all`, `any_of`, `numeric_gt`) OR LLM judge (for rubric questions, score ≥ 3/5). Bot prefers rubric when available, falls back to keywords.
2. **Source check** — if `expected_source` is set, the `source` field in agent output must match.
3. **Tool check** — if `check_tools` is set, the `tool_calls` array must include those tools.

## Spec thresholds

| Check ID | Questions | Threshold | Description |
|----------|-----------|-----------|-------------|
| `task3_local_eval` | 0-9 (local only) | 60% (6/10) | First pass gate |
| `task3_full_eval` | 0-19 (all) | 75% (15/20) | Final grade |

## Questions

### Class A — Wiki lookup

| # | Vis | Question | Answer check | Source check | Tools | Tier |
|---|-----|----------|-------------|-------------|-------|------|
| 0 | local | Steps to protect a branch on GitHub | `contains_all: [branch, protect]` | contains "wiki" | read_file | 1 |
| 1 | local | VM SSH connection steps | `any_of: [ssh, SSH, key, connect]` | contains "wiki" | read_file | 1 |
| 10 | hidden | Docker cleanup commands | `any_of: [prune, docker system prune, docker compose down, remove, clean]` | contains "wiki" | read_file | 1 |
| 11 | hidden | Swagger UI authorization | `any_of: [Bearer, API key, Authorize, LMS_API_KEY]` | contains "wiki" | read_file | 1 |

**What the agent needs to do:** Use `list_files` to discover wiki pages, then `read_file` to find the answer. Must set `source` to a wiki file path.

### Class B — Static system facts

| # | Vis | Question | Answer check | Source check | Tools | Tier |
|---|-----|----------|-------------|-------------|-------|------|
| 2 | local | Python web framework | `any_of: [FastAPI, fastapi]` | — | read_file | 1 |
| 3 | local | API router modules | `contains_all: [items, interactions, analytics, pipeline]` | — | list_files | 1 |
| 12 | hidden | Dockerfile image-size technique | `any_of: [multi-stage, multi stage, slim, two stage, builder]` | — | read_file | 1 |
| 13 | hidden | Database tables | `contains_all: [item, learner, interact]` | — | read_file | 1 |

**What the agent needs to do:** Use `read_file` or `list_files` on source code (backend/, Dockerfile). No API needed (tier 1).

### Class C — Data-dependent queries

| # | Vis | Question | Answer check | Source check | Tools | Tier |
|---|-----|----------|-------------|-------------|-------|------|
| 4 | local | Item count in database | `numeric_gt: 0` | — | query_api | 2 |
| 5 | local | Status code without auth | `any_of: [401, 403]` | — | query_api | 2 |
| 14 | hidden | Distinct learner count | `numeric_gt: 0` | — | query_api | 2 |
| 15 | hidden | Status for nonexistent endpoint | `contains: 404` | — | query_api | 2 |

**What the agent needs to do:** Use `query_api` with proper authentication. For Q5, must make an unauthenticated request. Needs running backend (tier 2).

### Class D — Bug diagnosis

| # | Vis | Question | Answer check | Source check | Tools | Tier |
|---|-----|----------|-------------|-------------|-------|------|
| 6 | local | completion-rate bug for lab-99 | `any_of: [ZeroDivisionError, division by zero, divide by zero]` | contains "analytics" | query_api, read_file | 2 |
| 7 | local | top-learners crash | `any_of: [TypeError, None, NoneType, sorted, comparison]` | contains "analytics" | query_api, read_file | 2 |
| 16 | hidden | How many endpoints have bugs | `contains_all: [completion, top]` | contains "analytics" | read_file | 2 |
| 17 | hidden | Compare working vs failing lab | `any_of: [ZeroDivisionError, division by zero, zero, no learners, empty]` | — | query_api, read_file | 2 |

**What the agent needs to do:** Chain `query_api` (trigger the error) → `read_file` (read analytics.py source) → explain the bug. Must set `source` to analytics file.

### Class E — LLM-judged reasoning

| # | Vis | Question | Keyword fallback | Rubric (bot LLM judge) | Tools | Tier |
|---|-----|----------|-----------------|----------------------|-------|------|
| 8 | local | HTTP request lifecycle | `contains_all: [caddy, fastapi, postgres]` | ≥4 of 6 hops: Caddy, FastAPI, auth, router, ORM, PostgreSQL | read_file | 2 |
| 9 | local | ETL idempotency | `any_of: [external_id, existing, duplicate, upsert, skip]` | Must mention external_id check, skip duplicates, upsert pattern | read_file | 2 |
| 18 | hidden | ETL vs API error handling | `contains_all: [etl, error]` | Describe both, compare, judge robustness | read_file | 2 |
| 19 | hidden | LMS_API_KEY auth flow | `contains_all: [docker-compose, LMS_API_KEY]` | ≥4 of 5 steps: .env → compose → config → dependency → header | read_file | 2 |

**What the agent needs to do:** Read multiple files, synthesize understanding, write a coherent explanation. Bot uses LLM judge with rubric (score ≥ 3/5); locally falls back to keyword check.

## Difficulty analysis

- **Easy** (tier 1, classes A+B): 8 questions — just read files, no API needed
- **Medium** (tier 2, classes C+D): 8 questions — need running backend + tool chaining
- **Hard** (tier 2, class E): 4 questions — need synthesis + clear explanation

A well-built agent with read_file + list_files + query_api should pass tier 1 easily (8/8). Tier 2 keyword questions (C+D) are achievable with proper tool schemas. Class E requires good system prompting for detailed explanations.

## Environment injected by autochecker

| Variable | Value on Hetzner | Purpose |
|----------|-----------------|---------|
| `LLM_API_KEY` | Groq API key | Student agent calls LLM |
| `LLM_API_BASE` | `https://api.groq.com/openai/v1` | LLM endpoint |
| `LLM_MODEL` | `llama-3.1-8b-instant` | Model for agent |
| `LMS_API_KEY` | `autochecker-eval-{port}` | Backend auth |
| `AGENT_API_BASE_URL` | `http://127.0.0.1:{random_port}` | Backend URL |

LLM judge uses separate credentials (`LLM_JUDGE_API_KEY`, `LLM_JUDGE_MODEL`) for rubric evaluation.
