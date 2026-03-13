# Autochecker

Automated student lab checker with Telegram bot and web dashboard.

## Components

- **autochecker/** — core check engine (GitHub/GitLab API, code checks, LLM analysis, plagiarism detection)
- **bot/** — Telegram bot (aiogram 3.x) for student self-service
- **dashboard/** — FastAPI web dashboard for instructors
- **specs/** — YAML lab specifications

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in tokens
```

### CLI — check a single student

```bash
python main.py check -s Nurassyl28 -l lab-01 -p github
```

### CLI — batch check

```bash
python main.py batch -s students.csv -l lab-01 -p github --workers 2
```

### Telegram bot

```bash
python main_bot.py
```

### Dashboard

```bash
uvicorn dashboard.app:app --host 0.0.0.0 --port 8000
```

## Project Structure

```
autochecker/                    # repo root
├── autochecker/                # core engine package
│   ├── __init__.py             # check_student() API
│   ├── __main__.py             # python -m autochecker
│   ├── cli.py                  # Typer CLI
│   ├── engine.py               # check engine (all check types)
│   ├── llm_analyzer.py         # LLM analysis via OpenRouter
│   ├── batch_processor.py      # parallel batch processing
│   ├── reporter.py             # HTML/JSONL report generation
│   ├── github_client.py        # GitHub API client
│   ├── gitlab_client.py        # GitLab API client
│   ├── repo_reader.py          # repo archive reader
│   ├── spec.py                 # YAML spec parser
│   └── plagiarism_checker.py   # plagiarism detection
├── bot/                        # Telegram bot
│   ├── allowed_emails.csv      # email whitelist with groups (from Moodle CSV)
│   ├── config.py               # bot configuration + whitelist loading
│   ├── database.py             # SQLite with migrations (v4)
│   ├── runner.py               # autochecker integration (direct import)
│   ├── keyboards.py            # inline keyboards
│   ├── middlewares.py          # auth middleware + whitelist enforcement
│   └── handlers/               # message/callback handlers
├── relay/                      # relay worker (runs on university VM)
│   └── worker.py               # WebSocket client, HTTP + SSH job executor
├── dashboard/                  # FastAPI dashboard
│   ├── app.py                  # routes, auth, relay endpoints
│   └── templates/              # Jinja2 HTML templates
├── specs/                      # lab YAML specs
├── docs/                       # internal documentation
│   ├── infrastructure.md       # network topology, SSH routing, relay
│   └── gotchas.md              # recurring bugs & surprising fixes
├── reports/                    # plagiarism analysis reports (date-stamped)
├── deploy/                     # Docker deployment
│   ├── Dockerfile              # bot + dashboard image (includes docker-ce-cli)
│   ├── Dockerfile.sandbox      # sandboxed student code runner
│   ├── docker-compose.yml
│   └── update.sh               # pull, verify, rebuild, restart
├── main.py                     # CLI entry point
├── main_bot.py                 # bot entry point
├── verify.py                   # pre-deploy verification (27 checks)
├── requirements.txt
├── .env.example
├── students.csv
├── CONTRIBUTING.md
└── MOODLE_GRADING_GUIDE.md
```

## Configuration

All config is via environment variables (`.env` file):

| Variable | Description | Default |
|---|---|---|
| `GITHUB_TOKEN` | GitHub API token | — |
| `GITLAB_TOKEN` | GitLab API token | — |
| `OPENROUTER_API_KEY` | OpenRouter API key for LLM checks | — |
| `LLM_MODEL` | LLM model identifier | `google/gemini-2.5-flash-lite` |
| `BOT_TOKEN` | Telegram bot token | — |
| `DB_PATH` | SQLite database path | `bot.db` |
| `ACTIVE_LABS` | Comma-separated active lab IDs | `lab-01` |
| `MAX_ATTEMPTS_PER_TASK` | Max check attempts per student per task | `3` |
| `DASHBOARD_PASSWORD` | Dashboard auth password (empty = no auth) | — |
| `RELAY_TOKEN` | Shared secret for relay worker ↔ dashboard auth | — |
| `RELAY_URL` | Relay WebSocket URL (worker config) | `wss://auche.namaz.live/relay/ws` |
| `SSH_KEY_PATH` | Path to SSH private key for `ssh_check` (direct mode) | `/app/ssh_key` |
| `SANDBOX_DIR` | Host directory for clone_and_run temp files | `/tmp/autochecker-sandbox` |

## Email Whitelist

Only emails listed in `bot/allowed_emails.csv` can register. The CSV has two columns (`email,group`) and is generated from the Moodle participants export. Loaded at startup in `bot/config.py` as `ALLOWED_EMAILS` (dict mapping email to group). Falls back to `allowed_emails.txt` (one email per line, no groups) if the CSV doesn't exist.

- **New registrations**: blocked at the email step if not in the list; group is auto-assigned from the CSV
- **Existing users**: evicted on next interaction if their email isn't in the list (middleware check in `bot/middlewares.py`)
- **Admins**: exempt from the whitelist (`is_admin = 1` in DB)
- **Group backfill**: on every startup, `init_db()` syncs groups from the CSV into existing users

To update the whitelist, replace `bot/allowed_emails.csv` and redeploy.

## Plagiarism Detection

The `batch` command includes cross-student plagiarism analysis. It runs **after** all students are checked, comparing their code and git histories.

### What it checks

1. **File similarity** — MD5 hashes of every source file, minus files identical to the template repo. Pairs exceeding the threshold are flagged.
2. **Git history** — cross-student comparison of:
   - **Shared commit SHAs** (critical) — identical commit objects = literal repo copy
   - **Identical commit messages** (high) — same non-trivial message across students
   - **Shared author emails** (medium) — one person's git email in another student's repo

### Noise reduction

The checker automatically filters out false positives:

| Filter | What it removes |
|---|---|
| Template file subtraction | Files identical to the upstream template repo (everyone starts with them) |
| Template commit exclusion | All commit SHAs and messages from the template (inherited by every fork) |
| Merge commit filtering | Author emails from `"Merge pull request"` commits (PR reviewers, not plagiarism) |
| Popularity threshold | File hashes, commit messages, or emails shared by >10% of students (prescribed fixes, lab-instructed messages) |
| Trivial message skip | Generic messages like `"initial commit"`, `"update readme.md"`, and messages <10 chars |

### Usage

```bash
# 1. Export student list (one GitHub username per line)
ssh nurios@188.245.43.68 "docker exec autochecker-bot python3 -c \"
import sqlite3
conn = sqlite3.connect('/app/data/bot.db')
for r in conn.execute('SELECT github_alias FROM users WHERE github_alias != \\\"\\\"').fetchall():
    print(r[0])
\"" > students.txt

# 2. Run batch check with plagiarism analysis
python main.py batch \
  -s students.txt \
  -l lab-03 \
  --template-repo inno-se-toolkit/se-toolkit-lab-3 \
  --plagiarism \
  --threshold 0.5 \
  -w 5 \
  -o /tmp/lab3-results
```

### CLI options

| Flag | Default | Description |
|---|---|---|
| `--plagiarism / --no-plagiarism` | on | Enable/disable plagiarism analysis |
| `--template-repo owner/name` | from spec | Upstream template repo for diff-based comparison |
| `--threshold 0.5` | `0.5` | Minimum file similarity ratio to flag a pair |

### Output files

| File | Description |
|---|---|
| `batch_summary.html` | Per-student scores and links to individual reports |
| `plagiarism_report.json` | All file-similarity pairs above threshold |
| `plagiarism_detailed_report.html` | Side-by-side file contents for flagged pairs |
| `git_plagiarism_flags.json` | All git history flags (shared SHAs, messages, emails) |
| `git_plagiarism_report.html` | Formatted table of git history flags |

### Interpreting results

- **Shared commit SHAs** (critical severity) are the strongest signal — they mean one student literally has another student's commit objects in their repo. This only happens via `git push` of someone else's history or cloning their repo.
- **File similarity** is useful but noisy for labs with prescribed fixes. After the popularity filter, only genuinely unusual matches remain. Look for pairs sharing 5+ non-template files.
- **Identical commit messages** are common when labs suggest specific conventional commit messages. The popularity filter removes these. Remaining matches (shared by 2-3 students) may indicate copying but need manual review.
- **Shared author emails** after merge-commit filtering means someone's git email appears in non-merge commits on another student's repo — i.e., one person authored code in both repos.

### Spec configuration

You can set plagiarism defaults in the lab YAML spec:

```yaml
plagiarism:
  template_repo: "inno-se-toolkit/se-toolkit-lab-3"
  threshold: 0.5
  include_paths:
    - "src/*"
  exclude_paths:
    - "docs/*"
  include_extensions:
    - ".py"
    - ".js"
```

### Deep investigation of flagged pairs

After the automated screening, investigate critical/high pairs with:

```bash
python scripts/investigate_pair.py \
  --student-a AleksKornilov07 --student-b venimu \
  --repo se-toolkit-lab-4 \
  --template inno-se-toolkit/se-toolkit-lab-4
```

This clones both repos + template and produces a structured report:

- **File comparison against template** — categorizes every file as template-unchanged, identical-modified (suspicious), or different
- **Git timeline** — who committed what, when (establishes who did the work first)
- **Cross-author analysis** — does student A's email appear as author of commits in student B's repo?
- **Shared commit SHAs** — same as batch but with full context
- **Source file diffs** — actual code differences for files that aren't identical
- **Non-ASCII scan** — flags unusual Unicode characters in source files (e.g. homoglyphs from keyboard layout switching)

Output: JSON report in `reports/investigations/`.

### Interpreting investigation results

| Evidence | Verdict |
|----------|---------|
| Shared commit SHAs + identical modified files + cross-author emails | **Confirmed** — one repo forked/merged from the other |
| `Merge pull request from <other-student>` in git log | **Confirmed** — direct merge |
| Many identical modified files, no shared SHAs, code diffs are trivial | **Probable** — manual copy, needs timeline review |
| Only shared commit messages + identical prescribed fixes | **Not plagiarism** — lab instructions produce identical output |
| Shared author email from merge commits only | **PR reviewer** — expected workflow |

### Known limitations

The automated screening catches students who fork, clone, or merge each other's repos (shared commit SHAs). It does **not** catch manual copy-paste where the student retypes code and commits under their own identity — those cases produce different commit SHAs and may produce slightly different file hashes. The investigation script helps with these via timeline analysis and file diffing, but they must be flagged through other means (TA reports, suspicious score patterns, etc).

### Reports directory

Analysis reports are saved in `reports/` with date-stamped directories (e.g. `reports/lab3-plagiarism-2026-02-27/`). These are not auto-generated — save them manually after review.

## Architecture

The bot imports `check_student()` from the `autochecker` package directly (no subprocess). This gives real Python exceptions, shared config, and eliminates disk I/O for result passing.

```
bot/runner.py  →  autochecker.check_student()  →  engine + LLM  →  StudentCheckResult
    ↓
bot/handlers/check.py reads result files + saves to SQLite
```

## Sandbox (clone_and_run)

Some checks (e.g. lab-02 `uv run poe test`) clone a student repo and run commands. These execute inside ephemeral Docker containers, isolated from the bot.

### How it works

1. Bot clones the repo into `/tmp/autochecker-sandbox/run_XXXX/` (host-visible path)
2. Bot spawns `docker run autochecker-sandbox:latest sh -c "uv sync && uv run poe test"` with the repo mounted
3. Container is destroyed after the run (`--rm`)

### Restrictions on student code

| Resource | Limit |
|---|---|
| RAM | 512 MB (`--memory=512m`) |
| CPU | 1 core (`--cpus=1`) |
| Processes | 256 (`--pids-limit=256`) |
| Linux capabilities | All dropped (`--cap-drop=ALL`) |
| Privilege escalation | Blocked (`--security-opt=no-new-privileges`) |
| Filesystem | Only their cloned repo directory is mounted |
| Bot env vars | Not accessible (separate container) |
| Bot database | Not accessible |
| Network | Allowed (needed for `uv sync` to install dependencies) |

### Files

- `deploy/Dockerfile.sandbox` — minimal image (Python 3.14 + git + uv)
- `deploy/Dockerfile` — bot image includes `docker-ce-cli` to spawn sandbox containers
- `deploy/docker-compose.yml` — mounts Docker socket + shared `/tmp/autochecker-sandbox`
- `autochecker/engine.py` — `check_clone_and_run()` → `_run_in_sandbox()` / `_run_direct()` fallback

### Fallback

When Docker is unavailable (local dev), commands run directly via `subprocess`. This is logged as `"All commands passed"` (no sandbox suffix).

## SSH Checks (ssh_check)

Some checks verify VM deployment by SSHing into student machines as `autochecker` and running commands (e.g. checking fail2ban, sshd config, running services).

### How it works

1. Student creates a `autochecker` user on their VM and adds the autochecker's public SSH key
2. Student provides their VM IP to the bot
3. Engine dispatches `ssh_check` → routes through relay worker (for internal 10.x.x.x IPs) or direct SSH (for public IPs)

### Spec params

```yaml
type: ssh_check
params:
  runtime: prod              # resolves server_ip from runtime config
  username: autochecker          # SSH user (default: autochecker)
  port: 22                    # SSH port (default: 22)
  command: "echo ok"          # command to run on the VM
  expect_exit: 0              # expected exit code (-1 = any non-zero)
  expect_regex: "ok"          # regex to match against stdout
  timeout: 10                 # seconds
```

### Routing: internal vs public IPs

The engine routes SSH and HTTP checks differently based on the student's IP:

| Student IP | Route | SSH key location |
|---|---|---|
| Internal (`10.93.x.x`) | Bot → Relay worker → Student VM | Relay VM: `~/.ssh/autochecker_ed25519` |
| Public (e.g. `92.x.x.x`) | Bot → direct SSH/HTTP → Student VM | Bot container: `/app/ssh_key` (mounted from `~/autochecker-ssh-key`) |

For relay-routed checks:
```
Engine → POST /relay/ssh → Dashboard → WebSocket → Relay Worker (university VM) → SSH → Student VM
```

**Known limitation**: The relay worker runs on `10.93.24.120` and can only reach the `10.93.x.x` subnet. Students on other internal subnets (e.g. `10.90.x.x`) cannot be reached — their deployment checks must be passed manually via the dashboard or DB.

For direct SSH checks, the bot container requires:
- `openssh-client` installed (in `deploy/Dockerfile`)
- SSH private key mounted at `/app/ssh_key` (in `deploy/docker-compose.yml`)

### SSH key setup

**Public key** (give to students for `autochecker`'s `authorized_keys`):
```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKiL0DDQZw7L0Uf1c9cNlREY7IS6ZkIbGVWNsClqGNCZ se-toolkit-autochecker
```

**Private key** location:
- Relay worker (university VM): `~/.ssh/autochecker_ed25519`
- Direct mode: path from `SSH_KEY_PATH` env var (default `/app/ssh_key`)

The private key is **never committed to git**.

## Relay Worker

The relay worker bridges the Hetzner server to the university network. It runs on a university VM and handles HTTP and SSH check jobs for internal IPs (10.x.x.x) that the bot can't reach directly.

### Architecture

```
┌─ Hetzner (188.245.43.68) ──────────────────────────────────┐
│  Bot Engine                                                 │
│   └─ POST /relay/check or /relay/ssh                       │
│        ↓                                                    │
│  Dashboard (FastAPI :8082)                                  │
│   └─ WebSocket ────────────────────────┐                   │
└────────────────────────────────────────│───────────────────┘
                                         │ wss://auche.namaz.live/relay/ws
┌─ University VM (10.93.24.120) ────────│───────────────────┐
│  Relay Worker (systemd service)  ←────┘                    │
│   ├─ HTTP jobs: curl to internal IPs                       │
│   └─ SSH jobs: ssh -i key autochecker@student-vm "command"    │
└────────────────────────────────────────────────────────────┘
```

### Resilience

The university network periodically kills WebSocket connections. The system handles this:
- **Worker**: auto-reconnects every 5 seconds on disconnect, ping interval 30s / timeout 60s
- **Dashboard**: `_send_relay_job()` waits up to 12 seconds for worker reconnection and retries once on timeout or stale connection
- **Engine**: `_ssh_check_via_relay()` and `_http_check_via_relay()` retry on 503/504 with 6-second backoff

### Deployment

The worker runs on the university VM as a systemd service:
- **Service**: `relay-worker.service`
- **Code**: `/home/deploy/relay/worker.py` (copied manually, not a git clone)
- **SSH key**: `/home/deploy/.ssh/autochecker_ed25519`
- **Env vars**: `RELAY_TOKEN`, `RELAY_URL` (set in systemd unit)

To update the worker:
```bash
scp relay/worker.py deploy@10.93.24.120:~/relay/worker.py
ssh deploy@10.93.24.120 "sudo systemctl restart relay-worker"
```

### Security

- Worker only accepts jobs targeting internal IPs (10.x, 172.16-31.x, 192.168.x)
- All endpoints require HMAC-verified bearer token
- SSH key has no sudo access on student VMs (autochecker user)
- Timeouts capped at 30 seconds, response bodies capped at 4KB

## Production Deployment

### Infrastructure

| Component | Host | Path / Container |
|---|---|---|
| Bot | `nurios@188.245.43.68` | `autochecker-bot` container |
| Dashboard | `nurios@188.245.43.68` | `autochecker-dashboard` container (port 8082) |
| Sandbox image | `nurios@188.245.43.68` | `autochecker-sandbox` (built, not running) |
| Nginx | `nurios@188.245.43.68` | `/etc/nginx/sites-enabled/auche.namaz.live` |
| SSH key (bot) | `nurios@188.245.43.68` | `~/autochecker-ssh-key` → mounted as `/app/ssh_key` (for direct SSH to public IPs) |
| Relay worker | `deploy@10.93.24.120` | `relay-worker.service` (`~/relay/worker.py`) |
| SSH key (relay) | `deploy@10.93.24.120` | `~/.ssh/autochecker_ed25519` (for SSH through relay to internal IPs) |
| Repo on server | `nurios@188.245.43.68` | `~/autochecker` (git clone) |

### Deploy a new version (Hetzner)

**Recommended**: use the automated script, which pulls, verifies, builds, and restarts:

```bash
ssh nurios@188.245.43.68
cd ~/autochecker
bash deploy/update.sh
```

**Manual steps** (if you need finer control):

```bash
ssh nurios@188.245.43.68
cd ~/autochecker

# 1. Pull latest code
git pull

# 2. (Optional) Run pre-deploy verification
docker build -f deploy/Dockerfile -t autochecker-verify . --quiet
docker run --rm autochecker-verify python verify.py

# 3. Build ALL images (bot, dashboard, sandbox)
#    IMPORTANT: always build before recreating — `docker compose up` alone reuses old images
cd deploy
docker compose build

# 4. Restart containers
docker compose up -d

# 5. Verify containers are running
docker compose ps
docker logs autochecker-bot --tail 20
docker logs autochecker-dashboard --tail 20
```

**Gotcha**: `docker compose up -d --force-recreate` without a preceding `docker compose build` will recreate the container from the **old** image. Code changes from `git pull` won't take effect. Always build first.

**Rebuild only specific services** (when you know what changed):

```bash
# Bot code changed (handlers, runner, config, engine)
docker compose build bot dashboard && docker compose up -d bot dashboard

# Sandbox image changed (Dockerfile.sandbox, Python version)
docker compose build sandbox

# Both
docker compose build && docker compose up -d
```

### Deploy relay worker (university VM)

```bash
scp relay/worker.py deploy@10.93.24.120:~/relay/worker.py
ssh deploy@10.93.24.120 "sudo systemctl restart relay-worker"
```

### Docker volumes and mounts

| Volume / Mount | Container | Contents |
|---|---|---|
| `deploy_bot-data` → `/app/data/` | bot, dashboard | `bot.db` (SQLite — users, attempts, results) |
| `deploy_autochecker-results` → `/app/results/` | bot | Per-student report files |
| `/var/run/docker.sock` | bot | Docker socket (for spawning sandbox containers) |
| `/tmp/autochecker-sandbox` | bot | Shared temp dir for clone_and_run repos |

### Check logs

```bash
# Hetzner
docker logs autochecker-bot --tail 50
docker logs autochecker-dashboard --tail 50

# University VM
ssh deploy@10.93.24.120 "sudo journalctl -u relay-worker --no-pager -n 50"
```

### Back up the database

```bash
docker cp autochecker-bot:/app/data/bot.db ./bot.db.backup
```

### Pre-deploy verification

```bash
python verify.py
```

Checks file structure, imports, path resolution, CLI commands, spec loading, no stale references, and deploy file correctness.

## Adding a New Lab Spec

Step-by-step guide for adding autochecker support for a new lab.

### 1. Create the spec file

Create `specs/lab-XX.yaml` with the lab's check definitions. See existing specs for structure reference and `CONTRIBUTING.md` for available check types.

```yaml
id: lab-XX
title: "Lab XX – Title"
repo_name: "se-toolkit-lab-X"

tasks:
  - id: setup
    title: "Lab setup"
  - id: task-1
    title: "Task 1: ..."
    prerequisite: setup

runtime:
  prod:
    base_url: "http://{server_ip}:42002"

checks:
  # Setup checks
  - id: setup_repo_exists
    task: setup
    type: repo_exists
    # ...

  # Task checks
  - id: t1_some_check
    task: task-1
    type: regex_in_file
    # ...
```

### 2. Register the lab in the CLI

Edit `autochecker/cli.py` and add an entry to `LAB_CONFIG`:

```python
"lab-XX": {
    "repo_suffix": "se-toolkit-lab-X",
    "name": "Lab XX – Title",
    "ready": True,
},
```

### 3. Activate the lab in the bot

On the server, update `deploy/.env`:

```bash
# Add the new lab to the comma-separated list
ACTIVE_LABS=lab-01,lab-02,lab-03,lab-04
```

### 4. Validate the spec

```bash
# Check that the spec parses correctly
python -c "from autochecker.spec import load_spec; s = load_spec('specs/lab-XX.yaml'); print(f'{len(s[\"checks\"])} checks loaded')"

# Test against a known student repo
python main.py check -s <student-username> -l lab-XX -p github
```

### 5. Deploy

```bash
ssh nurios@188.245.43.68
cd ~/autochecker
git pull
cd deploy
docker compose build && docker compose up -d
docker logs autochecker-bot --tail 20  # verify bot started with new lab
```

### 6. Verify on the bot

- Open the Telegram bot
- The new lab should appear in the lab selection menu
- Run a check to confirm it works end-to-end

### Runtime checks (VM deployment)

If the lab has checks that target student VMs (`runtime: prod` in params), the bot will automatically prompt students for their VM IP. The IP is stored per-student and reused across checks. The engine resolves `{server_ip}` in `base_url` at check time.

For internal IPs (10.x.x.x), checks are routed through the relay worker on the university VM. Ensure the relay worker is running (see [Deploy relay worker](#deploy-relay-worker-university-vm)).

### Sandbox (clone_and_run) checks

If the lab has `clone_and_run` checks, ensure the sandbox image supports the lab's Python version. The sandbox Dockerfile is at `deploy/Dockerfile.sandbox` (currently Python 3.14). If a lab needs a different runtime, update the Dockerfile and rebuild:

```bash
cd deploy
docker compose build sandbox
```

### Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Bot doesn't show the new lab | `ACTIVE_LABS` not updated | Add lab ID to `ACTIVE_LABS` in `deploy/.env`, restart |
| "No spec found" error | Spec file missing or `ready: False` in CLI | Check `specs/lab-XX.yaml` exists and `cli.py` entry |
| Checks show `localhost` instead of student IP | Spec missing `runtime: prod` on check params | Add `runtime: prod` to checks that need student VM access |
| `clone_and_run` exit code 2 | Import errors in student code | Ensure spec commands set required env vars (e.g. `API_TOKEN=test`) |
| Container has old code after deploy | Forgot to `docker compose build` | Always build before `up -d` |
| Dashboard doesn't reflect new lab | Dashboard container not rebuilt | Rebuild dashboard: `docker compose build dashboard && docker compose up -d dashboard` |
| "SSH key not found at /app/ssh_key" | SSH private key not mounted into bot container | Save key to `~/autochecker-ssh-key` on server, verify `docker-compose.yml` mounts it |
| SSH exit code 255 for public IP students | `openssh-client` not in Dockerfile, or key not mounted | Check `deploy/Dockerfile` has `openssh-client`, rebuild |
| SSH timeout for `10.90.x.x` students | Relay worker on `10.93.x.x` can't route to `10.90.x.x` | Pass deployment checks manually; no fix without a second relay |
| HTTP expect_status mismatch (e.g. expected 403 got 401) | App returns different auth error code than spec expects | Verify actual response with `curl`, update spec `expect_status` |
| Student IP typo (e.g. `0.93.x.x` instead of `10.93.x.x`) | Mistyped IP during bot registration | Fix via dashboard or DB: `UPDATE users SET server_ip = '...' WHERE github_alias = '...'` |

## License

MIT
