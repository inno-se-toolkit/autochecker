# Deploy Checklist

Run through this before every deploy to Hetzner. Most issues we've hit were caused by skipping one of these steps.

## Before deploying

- [ ] **Run tests locally**: `cd autochecker && pytest tests/ -v`
- [ ] **Run verify.py**: `python verify.py` (or let `update.sh` do it — but check output)
- [ ] **Check if relay worker needs updating**: Did you change `relay/worker.py`? If yes, you must manually deploy it (see [Relay worker](#relay-worker) below)
- [ ] **Check if spec changes break the dependency chain**: Every `depends_on` must reference an existing check ID. Every `agent_eval` check must have `eval_lab`, `min_pass_rate`, and `sample_per_class` in params
- [ ] **Don't deploy during class hours if possible**: Each deploy restarts the dashboard container, which disconnects the relay worker's WebSocket for 5-30 seconds. Student checks during that window will fail with "Relay worker not connected"

## Deploy

```bash
ssh nurios@188.245.43.68
cd ~/autochecker && bash deploy/update.sh
```

## After deploying

- [ ] **Check containers are running**: `docker compose -f deploy/docker-compose.yml ps`
- [ ] **Check relay reconnected**:
  ```bash
  docker exec autochecker-bot curl -s \
    -H "Authorization: Bearer $RELAY_TOKEN" \
    http://dashboard:8000/relay/status
  ```
  Should return `{"worker_connected": true}`. If not, restart the relay worker on the university VM (see below).
- [ ] **Check ACTIVE_LABS**: `docker exec autochecker-bot env | grep ACTIVE_LABS` — make sure the new lab is listed
- [ ] **Spot-check a student**: Run a quick check from the bot to verify the full flow works

## Relay worker

The relay worker runs on university VM `10.93.24.120` as a systemd service. It is **not** auto-deployed — you must update it manually.

### When to update
- You changed `relay/worker.py`
- You changed the WebSocket protocol in `dashboard/app.py` relay endpoints

### How to update
```bash
# From your local machine (must be on university network or VPN)
scp relay/worker.py deploy@10.93.24.120:/home/deploy/relay/worker.py
ssh deploy@10.93.24.120 "sudo systemctl restart relay-worker"
ssh deploy@10.93.24.120 "sudo systemctl status relay-worker"
```

### If relay is down
```bash
ssh deploy@10.93.24.120 "sudo systemctl restart relay-worker"
# Then verify from Hetzner:
ssh nurios@188.245.43.68 "docker exec autochecker-bot curl -s \
  -H 'Authorization: Bearer \$RELAY_TOKEN' \
  http://dashboard:8000/relay/status"
```

### Why does the relay go down?
Every `docker compose up -d` on Hetzner restarts the dashboard container, which sends a WebSocket close (code 1012) to the relay worker. The worker has retry logic and usually reconnects within 5 seconds, but:
- If the dashboard takes >10s to start, the worker gets HTTP 502 on reconnect attempts
- Multiple rapid deploys can exhaust the reconnect timing window
- The worker process stays alive but the WebSocket stays disconnected

### Health check cron (auto-recovery)
A cron job runs every minute on the university VM (`deploy` user) that tests real relay connectivity and restarts the worker if it fails:
```
* * * * * /home/deploy/relay/health_check.sh
```
The script does a real SSH `echo ok` through the relay (not `/relay/status` which was unreliable). Only restarts if the actual SSH test fails.

To check health check logs:
```bash
# Via relay from Hetzner
docker exec autochecker-bot python3 -c "..."  # SSH to 10.93.24.120, run journalctl -t relay-health

# Direct (if you have VPN/university access)
ssh deploy@10.93.24.120 "sudo journalctl -t relay-health --since '1 hour ago'"
```

### Relay architecture notes
- Worker processes SSH jobs **concurrently** (asyncio.create_task), not sequentially
- Dashboard does NOT clear `_relay_worker` on job timeouts — only on actual connection errors
- Ping interval: 20s, timeout: 30s (worker side)
- SCP path: `scp autochecker/relay/worker.py deploy@10.93.24.120:~/relay/worker.py`

## Common pitfalls

| Pitfall | How to avoid |
|---------|-------------|
| `deploy/.env` not updated after adding a new lab | Edit `deploy/.env` on Hetzner, not just `.env.example`. Then `docker compose build && docker compose up -d` (NOT just `restart`) |
| `docker compose restart` doesn't re-read `.env` | Always use `docker compose up -d` |
| `docker compose up -d` reuses old image | Always `docker compose build` first |
| Relay stays disconnected after deploy | Check relay status. If disconnected, restart relay-worker on university VM |
| Spec change breaks eval | Run `pytest tests/test_agent_eval.py -v` before deploying — it validates spec structure |
| Student sees "No VM registered" for agent_eval | `get_tasks_needing_lms_key()` must return the task. Check that `agent_eval` check type exists in the spec for that task |
| Reset attempts needed after breaking change | Use the safe script: `docker exec autochecker-bot python3 scripts/reset_attempts.py --lab lab-06 --task task-3 --dry-run` (always dry-run first!) |
| Bot unresponsive after deploy | Restart bot: `docker compose up -d bot`. Check logs for `TelegramBadRequest` backlog |
| Relay times out under load | Worker must process jobs concurrently. Check worker version: `ssh deploy@10.93.24.120 "head -5 ~/relay/worker.py"` |

## Environment files

| File | Location | Purpose |
|------|----------|---------|
| `deploy/.env` | Hetzner `~/autochecker/deploy/.env` | Bot + dashboard config (tokens, active labs) |
| `deploy/.env.example` | Repo | Template — keep in sync with `.env` |
| `.env.docker.secret` | Student VMs | Backend (LMS_API_KEY, autochecker creds) |
| `.env.agent.secret` | Student VMs | LLM access (LLM_API_KEY, LLM_API_BASE_URL, LLM_API_MODEL) |
