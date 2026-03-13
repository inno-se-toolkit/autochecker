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
