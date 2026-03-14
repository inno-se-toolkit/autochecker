# Recurring Bugs & Gotchas

Fixes that have been applied more than once, or surprising behaviour worth remembering before writing new code.

---

## PostgreSQL `round()` requires `Numeric`, not `double precision`

**Symptom:** `ProgrammingError: function round(double precision, integer) does not exist`

**Root cause:** PostgreSQL's `round(x, n)` two-argument form only accepts `numeric`, not `double precision`. SQLAlchemy's `func.avg()` returns `double precision`.

**Fix:** cast the aggregation result to `Numeric` before rounding:

```python
from sqlalchemy import cast, func, Numeric

# Wrong — crashes on PostgreSQL
func.round(func.avg(col), 1)

# Correct
func.round(cast(func.avg(col), Numeric), 1)
```

**Where we hit this:** Lab 5 dashboard analytics, Lab 6 analytics router (`pass-rates`, `groups`). Both times the same fix was needed.

---

## stdout truncation — always keep from the start, never from the end

**Symptom:** `Invalid JSON` / `No JSON in output` errors during agent eval even though the agent produced valid JSON.

**Root cause:** Capturing `stdout[-4096:]` (tail) instead of `stdout[:65536]` (head) cuts off the JSON opening `{`. The grading code scans for lines starting with `{`, so it finds nothing.

**Fix:** Always truncate from the start:

```python
# Wrong — cuts off the opening brace
result.stdout[-4096:]

# Correct
result.stdout[:65536]
```

**Where we hit this:** Relay worker (`relay/worker.py`) and engine SSH eval. Both places were independently using tail truncation.

---

## Relay worker stdout limit needs manual deployment

The relay worker runs on the university VM `10.93.24.120` as a systemd service and is **not** auto-deployed from Hetzner. After changing `relay/worker.py`, you must:

```bash
scp autochecker/relay/worker.py root@10.93.24.120:/opt/relay/worker.py
ssh root@10.93.24.120 systemctl restart relay-worker
```

The stdout limit is currently `65536` bytes. If increased again, repeat the above.

---

## SSH routing: public IPs must use direct SSH, not relay

The relay only accepts internal university IPs (`10.x.x.x`). Routing a public IP through the relay causes a `Host not allowed` error — not immediately obvious because the relay returns 200 with an error body.

**Routing logic in `engine.py`:**

```python
if not host.startswith("10."):
    return self._direct_ssh(host, port, username, command, timeout)
# else: send through relay
```

`_direct_ssh()` uses `subprocess.run(["ssh", "-i", "/app/ssh_key", ...])` from inside the bot container. The container needs `openssh-client` installed and the key mounted at `/app/ssh_key`.

---

## Variable naming: grep all references when renaming

**Symptom:** `NameError: name 'ip' is not defined` in a bot handler, crashing the entire IP-save flow.

**Root cause:** When refactoring a callback handler, one variable reference was missed. The fix used `text` everywhere except one `{ip}` in an f-string.

**Rule:** Before saving a rename, `grep -n 'old_name'` in the file to confirm zero remaining occurrences.

---

## Agent eval: strip tool results from JSON output

Agent eval checks parse the JSON printed to stdout. If tool call results are included in the JSON, output easily exceeds the relay's 64 KB limit, causing truncation errors.

**Fix:** In the agent's output JSON, include only `{"tool": name, "args": args}` — not the result text:

```python
compact_calls = [
    {"tool": tc["tool"], "args": tc["args"]}
    # no "result" key
    for tc in all_tool_calls
]
```

Also cap what the agent sends to the LLM: `content: result[:15000]` to avoid filling the context window with large API responses.

---

## GitHub `/issues` API returns pull requests too

**Symptom:** `issue_has_linked_pr` check fails saying "issue #N is not closed" even though the PR body contains `Closes #N`. Happens when a PR has the exact same title as an issue.

**Root cause:** GitHub's `GET /repos/:owner/:repo/issues` endpoint returns both issues **and** pull requests. The engine was finding the PR by title-regex match, treating it as the issue, and then looking for a PR that closes the PR number — which doesn't exist.

**Fix:** Filter out items that have a `pull_request` key from `get_issues()`:

```python
all_items = self._get("issues?state=all&per_page=100") or []
return [i for i in all_items if "pull_request" not in i]
```

**Where we hit this:** Lab 6, student had PR #6 titled identically to issue #5.

---

## agent_eval: server_ip not passed for tasks without `runtime: prod`

**Symptom:** `No VM registered` error for task-3 even though the student has a VM IP saved. Eval never runs via SSH.

**Root cause:** `get_tasks_needing_ip()` only returns tasks that have a check with `params.runtime: prod`. The `agent_eval` check has no `runtime: prod`, so `server_ip` is never fetched from DB and is passed as `None` to the engine. The engine then sees `use_ssh = False` and falls back (or returns the error).

**Fix:** In `bot/handlers/check.py`, also fetch `server_ip` for tasks in `get_tasks_needing_lms_key()`:

```python
if task_id in get_tasks_needing_ip(lab_id) or task_id in get_tasks_needing_lms_key(lab_id):
    server_ip = await get_server_ip(db_user.tg_id)
```

**Where we hit this:** Lab 6 task-3 — every student's eval was silently broken.

---

## agent_eval: Windows CRLF in `.env.agent.secret` breaks `source`

**Symptom:** Agent exits with code 1: `.env.agent.secret: line N: //openrouter.ai/api/v1: No such file or directory`. Agent falls back to OpenRouter default URL, gets 403.

**Root cause:** Students who create `.env.agent.secret` on Windows get CRLF line endings. When bash `source`s the file, line `LLM_API_BASE=https:\r` is cut at `\r`, leaving `//openrouter.ai/api/v1` as a bare command on the next line — which bash tries to execute as a file path.

**Fix:** Strip carriage returns before sourcing:

```bash
# Wrong — breaks on Windows-created files
set -a && source .env.agent.secret && set +a

# Correct
set -a && . <(tr -d '\r' < .env.agent.secret) && set +a
```

**Where we hit this:** Lab 6 task-3 — affected every student who created the env file on Windows.

---

## Qwen proxy HOST_PORT vs internal PORT

**Symptom:** `curl http://127.0.0.1:8080/v1/models` returns nothing (connection refused) even though the Qwen proxy container is running.

**Root cause:** The `qwen-code-oai-proxy` docker-compose maps `HOST_PORT` (e.g. `42005`) → container port `PORT` (e.g. `8080`). From the VM host, the proxy is reachable at `HOST_PORT`, not `PORT`. The `.env.agent.secret` must use the host port.

**How to check:** `ss -tlnp | grep node` — look for the listening port. Or check `HOST_PORT` in `~/qwen-code-oai-proxy/.env`.

**Where we hit this:** Lab 6, nurlingo had `LLM_API_BASE=http://127.0.0.1:8080/v1` but proxy was on `42005`.

---

## Always scope DELETE queries with `lab_id`

**Symptom:** All lab-05 task-3 results vanished after resetting lab-06 task-3 attempts.

**Root cause:** `DELETE FROM results WHERE task_id = 'task-3'` — no `lab_id` filter. This deleted task-3 results across **all labs**.

**Rule:** Every DELETE on `results` or `attempts` must include both `lab_id` and `task_id`:

```sql
-- Wrong — nukes task-3 across all labs
DELETE FROM results WHERE task_id = 'task-3';

-- Correct
DELETE FROM results WHERE lab_id = 'lab-06' AND task_id = 'task-3';
```

**Where we hit this:** Resetting lab-06 task-3 attempts accidentally wiped lab-05 task-3 completions from March 6-7. No recovery possible.

---

## Relay: don't clear `_relay_worker` on job timeout

**Symptom:** ALL relay SSH requests return 503 "no worker connected" even though the WebSocket is open and the relay worker is running fine on the university VM.

**Root cause:** In `dashboard/app.py`, `_send_relay_job()` was setting `_relay_worker = None` on `asyncio.TimeoutError`. A single slow SSH job (e.g., student VM taking 30s to respond) would trigger a timeout, which cleared the worker reference, breaking ALL subsequent requests — even though the WebSocket was still alive.

**Fix:** Only clear `_relay_worker` on actual connection errors (exceptions from `ws.send_json`), never on timeouts:

```python
# Wrong — kills relay for everyone on a single slow job
except asyncio.TimeoutError:
    _relay_worker = None  # DON'T DO THIS

# Correct — timeout is just a slow job, not a dead connection
except asyncio.TimeoutError:
    logger.warning("Relay job %s timed out", job_id)
    return JSONResponse({"error": "worker timeout", ...}, status_code=504)
```

**Where we hit this:** March 14, 2026 — relay appeared down for hours but was actually connected. Every timeout cascaded into breaking all requests.

---

## Relay worker: process jobs concurrently, not sequentially

**Symptom:** Relay SSH requests time out under moderate load (5+ students running checks simultaneously), even though the worker is connected and responsive.

**Root cause:** The relay worker's message loop `await`ed each job before reading the next WebSocket message. One slow SSH job blocked all others:

```python
# Wrong — sequential, blocks the message loop
async for raw in ws:
    job = json.loads(raw)
    result = await loop.run_in_executor(None, _do_ssh_check, job)  # blocks here
    await ws.send(json.dumps(result))
```

**Fix:** Fire-and-forget with `asyncio.create_task()`:

```python
# Correct — concurrent, message loop stays free
async for raw in ws:
    job = json.loads(raw)
    asyncio.create_task(_handle_job(ws, job))
```

**Where we hit this:** March 14, 2026 — every lab-06 check session. 10+ students triggered SSH jobs simultaneously; each job blocked the next.

---

## Health check cron: test real connectivity, not `/relay/status`

**Symptom:** Relay worker restarts every 1-2 minutes even when it's working fine. Constant connect/disconnect cycle in dashboard logs.

**Root cause:** The health check cron script checked `GET /relay/status` which returned `{"worker_connected": false}` even when the worker was connected (due to the `_relay_worker = None` bug above). The cron restarted the worker, which briefly connected, then the next cron run saw false again and restarted it — creating an infinite restart loop.

**Fix:** Test actual SSH connectivity instead of the status endpoint:

```bash
# Wrong — status endpoint was unreliable
curl -s https://auche.namaz.live/relay/status | grep 'worker_connected.*true'

# Correct — actually test SSH through the relay
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -d '{"host":"10.93.24.120","port":22,"username":"deploy","command":"echo ok","timeout":5}' \
  https://auche.namaz.live/relay/ssh | grep '"exit_code":0'
```

**Where we hit this:** March 14, 2026 — cron was the primary cause of relay instability for hours.

---

## Student VM: root SSH fails if `/root` is world-writable

**Symptom:** SSH as root fails with `Permission denied (publickey,password)` even though the correct key is in `/root/.ssh/authorized_keys` with proper permissions.

**Root cause:** SSH refuses key authentication if the user's home directory is world-writable (`chmod 777`). This is a security check in OpenSSH — if anyone can write to `$HOME`, they could replace `authorized_keys`.

**Fix:**
```bash
chmod 755 /root
```

**How to debug student SSH issues:**
1. Check `vm_username` in DB: `SELECT vm_username, server_ip FROM users WHERE github_alias = '...'`
2. Try SSH as that user via relay
3. If denied, check: key match, `.ssh` permissions (700), `authorized_keys` permissions (600), home dir permissions (not 777), `PermitRootLogin` in sshd_config

**Where we hit this:** Student vyacheslavik07, March 14, 2026.

---

## Numeric regex: `[\d.]+` matches lone dots

**Symptom:** `ValueError: could not convert string to float: '.'` in `run_eval.py` answer matching.

**Root cause:** Regex `[\d.]+` matches a standalone `.` character (e.g., from sentence-ending punctuation). `float('.')` then crashes.

**Fix:** Use a regex that requires at least one digit:

```python
# Wrong — matches lone dots
numbers = re.findall(r"[\d.]+", text)

# Correct — requires at least one digit
numbers = re.findall(r"\d+(?:\.\d+)?", text)
```

**Where we hit this:** Lab 6, `run_eval.py` question 4 (numeric_gt check). Fixed in both upstream and forked repos.

---

## Bot: catch `TelegramBadRequest` on message edits

**Symptom:** Bot becomes unresponsive — ignores button presses, lab selection, task selection.

**Root cause:** When a student taps the same button twice quickly, Telegram rejects the `edit_message_text` call because the content is identical. The unhandled `TelegramBadRequest` exception crashes the handler, and aiogram's event loop gets backed up processing the accumulated update queue (one update took 19 minutes).

**Fix:** Wrap `edit_text` calls in `try/except TelegramBadRequest: pass`:

```python
from aiogram.exceptions import TelegramBadRequest

try:
    await callback.message.edit_text("...", reply_markup=keyboard)
except TelegramBadRequest:
    pass
```

**Where we hit this:** March 14, 2026 — bot was unresponsive during peak lab-06 usage.
