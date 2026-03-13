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
