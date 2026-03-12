# Infrastructure constraints

Course-wide constraints that affect how the autochecker runs checks against student work.

## Dev server (Hetzner, Germany)

- Runs the autochecker bot, Telegram bot, and all evaluation checks.
- Has internet access: Groq API, OpenRouter, Docker Hub, GitHub, PyPI.
- Cannot reach university VM IPs (10.x.x.x) directly — must go through relay.
- Has Docker available for sandboxed `clone_and_run` execution.
- IP: `188.245.43.68`.

## University VMs (10.x.x.x, Russia)

- Each student has a VM on the university internal network (10.93.x.x or similar).
- Only reachable from dev server via relay worker.
- **Most external LLM APIs are unreachable from Russia** (Groq, OpenAI, Anthropic). OpenRouter works but with rate limits.
- Docker Hub pulls are rate-limited on university network — use harbor proxy (`harbor.pg.innopolis.university/docker-hub-cache/`).
- 10.90.x.x subnet is unreachable even from relay (different network segment, ~3 students affected).

## Relay worker

- Runs on university VM `10.93.24.120` as a systemd service (`relay-worker.service`).
- Connects to dev server via WebSocket tunnel.
- Autochecker routes SSH commands to internal IPs through relay automatically (when `RELAY_TOKEN` is set).
- **Supports:** SSH command execution (run a command, get stdout/stderr/exit code).
- **Does not support:** HTTP proxying, TCP port forwarding, persistent tunnels.

## Networking matrix

| Need | From Hetzner | From university VM |
|------|-------------|-------------------|
| Call Groq/OpenAI API | Yes | No |
| Call OpenRouter API | Yes | Yes (rate-limited) |
| Reach student VM (10.x.x.x) | Via relay (SSH only) | Yes (direct) |
| Pull from Docker Hub | Yes | Rate-limited |
| Pull from harbor proxy | No (university network only) | Yes |
| Access GitHub API | Yes | Yes |
| Access autochecker API | Yes (localhost) | Yes (public URL) |

## Implications for lab design

### When student code needs an LLM

The autochecker cannot run LLM-dependent student code on the student's VM (LLM APIs blocked in Russia). Options:

1. **clone_and_run on Hetzner** — clone student repo, run their code on dev server with our LLM key injected via env vars. Student code must read LLM config from environment variables.
2. **SSH to VM, use OpenRouter** — works but burns student's free-tier quota (50 RPD). Not recommended for grading.

### When student code needs a running backend

If the student's code queries their own backend (e.g., an API tool):

- **On student VM:** backend runs on localhost, but LLM calls fail from Russia.
- **On Hetzner via clone_and_run:** clone repo, `docker compose up` the backend on Hetzner, student code queries localhost. LLM calls work. This is the preferred approach.
- **Split execution** (SSH for backend, Hetzner for LLM): requires HTTP proxying through relay, which is not supported. Avoid this.

### When checking without code execution

For tasks that don't need execution, use repo-level checks only:

| Check type | What it verifies |
|-----------|-----------------|
| `file_nonempty` | Deliverable files exist |
| `regex_in_file` | Code structure (tool names, patterns) |
| `glob_exists` | Test files exist |
| `file_word_count` | Documentation meets minimum length |
| `issue_exists` | Git workflow (issue created) |
| `issue_has_linked_pr` | PR closes issue, is merged |
| `issue_pr_approved` | PR has approvals |
| `commit_message_regex` | Commit conventions |

These checks are fast, don't require SSH or code execution, and don't consume any API quotas.
