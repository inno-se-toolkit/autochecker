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
│   ├── engine.py               # check engine
│   ├── llm_analyzer.py         # LLM analysis via OpenRouter
│   ├── batch_processor.py      # parallel batch processing
│   ├── reporter.py             # HTML/JSONL report generation
│   ├── github_client.py        # GitHub API client
│   ├── gitlab_client.py        # GitLab API client
│   ├── repo_reader.py          # repo archive reader
│   ├── spec.py                 # YAML spec parser
│   └── plagiarism_checker.py   # plagiarism detection
├── bot/                        # Telegram bot
│   ├── config.py               # bot configuration
│   ├── database.py             # SQLite with migrations
│   ├── runner.py               # autochecker integration (direct import)
│   ├── keyboards.py            # inline keyboards
│   ├── middlewares.py          # auth middleware
│   └── handlers/               # message/callback handlers
├── dashboard/                  # FastAPI dashboard
│   ├── app.py                  # routes and auth
│   └── templates/              # Jinja2 HTML templates
├── specs/                      # lab YAML specs
├── deploy/                     # Docker deployment
│   ├── Dockerfile              # bot + dashboard image
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

## Email Whitelist

Only emails listed in `bot/allowed_emails.txt` can register. The file is one email per line, extracted from the Moodle grades CSV. Loaded at startup in `bot/config.py` as `ALLOWED_EMAILS`.

- **New registrations**: blocked at the email step if not in the list
- **Existing users**: evicted on next interaction if their email isn't in the list (middleware check in `bot/middlewares.py`)
- **Admins**: exempt from the whitelist (`is_admin = 1` in DB)

To update the whitelist, replace `bot/allowed_emails.txt` and redeploy.

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

- `deploy/Dockerfile.sandbox` — minimal image (Python 3.13 + git + uv)
- `deploy/Dockerfile` — bot image includes `docker-ce-cli` to spawn sandbox containers
- `deploy/docker-compose.yml` — mounts Docker socket + shared `/tmp/autochecker-sandbox`
- `autochecker/engine.py` — `check_clone_and_run()` → `_run_in_sandbox()` / `_run_direct()` fallback

### Fallback

When Docker is unavailable (local dev), commands run directly via `subprocess`. This is logged as `"All commands passed"` (no sandbox suffix).

## SSH Checks (ssh_check)

Some checks verify VM deployment by SSHing into student machines as `checkbot` and running commands (e.g. checking fail2ban, sshd config, running services).

### How it works

1. Student creates a `checkbot` user on their VM and adds the autochecker's public SSH key
2. Student provides their VM IP to the bot
3. Engine dispatches `ssh_check` → routes through relay worker (for internal 10.x.x.x IPs) or direct SSH (for public IPs)

### Spec params

```yaml
type: ssh_check
params:
  runtime: prod              # resolves server_ip from runtime config
  username: checkbot          # SSH user (default: checkbot)
  port: 22                    # SSH port (default: 22)
  command: "echo ok"          # command to run on the VM
  expect_exit: 0              # expected exit code (-1 = any non-zero)
  expect_regex: "ok"          # regex to match against stdout
  timeout: 10                 # seconds
```

### Relay routing (internal IPs)

For university VMs (10.x.x.x), SSH checks go through the relay worker:
```
Engine → POST /relay/ssh → Dashboard → WebSocket → Relay Worker (university VM) → SSH → Student VM
```

### SSH key setup

**Public key** (give to students for `checkbot`'s `authorized_keys`):
```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKiL0DDQZw7L0Uf1c9cNlREY7IS6ZkIbGVWNsClqGNCZ se-toolkit-autochecker
```

**Private key** location:
- Relay worker (university VM): `~/.ssh/autochecker_ed25519`
- Direct mode: path from `SSH_KEY_PATH` env var (default `/app/ssh_key`)

The private key is **never committed to git**.

## Production Deployment

**Server:** `nurios@188.245.43.68`
**Repo on server:** `~/autochecker`
**Containers:** `autochecker-bot`, `autochecker-dashboard` (port 8082)

### Deploy a new version

```bash
ssh nurios@188.245.43.68
cd ~/autochecker
bash deploy/update.sh
```

The script:
1. `git pull`
2. Runs `verify.py` inside a container (27 checks must pass)
3. Rebuilds and restarts bot + dashboard containers

### Docker volumes

| Volume | Mount | Contents |
|---|---|---|
| `deploy_bot-data` | `/app/data/` | `bot.db` (SQLite — users, attempts, results) |
| `deploy_autochecker-results` | `/app/results/` | Per-student report files |

### Check logs

```bash
docker logs autochecker-bot --tail 50
docker logs autochecker-dashboard --tail 50
```

### Back up the database

```bash
docker cp autochecker-bot:/app/data/bot.db ./bot.db.backup
```

### Pre-deploy verification

Run locally or inside a container:
```bash
python verify.py
```

This checks file structure, imports, path resolution, CLI commands, spec loading, no stale references, and deploy file correctness. All 27 checks must pass.

## License

MIT
