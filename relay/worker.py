"""Thin relay worker that runs on the university VM.

Connects to the dashboard WebSocket, receives HTTP check jobs,
executes them locally (where internal 10.x.x.x IPs are reachable),
and sends results back.

Usage:
    RELAY_TOKEN=<secret> RELAY_URL=wss://auche.namaz.live/relay/ws python -m relay.worker
"""

import asyncio
import json
import logging
import os
import re
import subprocess
import sys

import websockets

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("relay-worker")

TOKEN = os.environ.get("RELAY_TOKEN", "")
SERVER = os.environ.get("RELAY_URL", "wss://auche.namaz.live/relay/ws")
RECONNECT_DELAY = 5

# Only allow requests to private/internal IPs
_INTERNAL_RE = re.compile(
    r"^https?://(10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3})"
)


def _is_allowed_url(url: str) -> bool:
    return bool(_INTERNAL_RE.match(url))


def _do_check(job: dict) -> dict:
    """Execute an HTTP check via curl and return the result."""
    job_id = job["job_id"]
    url = job.get("url", "")
    timeout = min(job.get("timeout", 10), 30)  # cap at 30s

    if not _is_allowed_url(url):
        return {"job_id": job_id, "status_code": 0, "body": "", "error": f"URL not allowed: {url}"}

    try:
        result = subprocess.run(
            ["curl", "-s", "-w", "\n%{http_code}", "--connect-timeout", str(timeout), url],
            capture_output=True, text=True, timeout=timeout + 5,
        )
        output = result.stdout
        lines = output.rsplit("\n", 1)
        body = lines[0] if len(lines) > 1 else ""
        status_str = lines[-1].strip() if lines else "0"

        try:
            status_code = int(status_str)
        except ValueError:
            status_code = 0

        return {
            "job_id": job_id,
            "status_code": status_code,
            "body": body[:4096],  # cap body size
            "error": result.stderr.strip() if result.returncode != 0 else "",
        }
    except subprocess.TimeoutExpired:
        return {"job_id": job_id, "status_code": 0, "body": "", "error": "timeout"}
    except Exception as e:
        return {"job_id": job_id, "status_code": 0, "body": "", "error": str(e)}


async def _run_worker():
    while True:
        try:
            log.info("Connecting to %s ...", SERVER)
            async with websockets.connect(
                SERVER, close_timeout=5, ping_interval=20, ping_timeout=20,
            ) as ws:
                # Authenticate
                await ws.send(json.dumps({"type": "auth", "token": TOKEN}))
                ack = json.loads(await ws.recv())
                if ack.get("type") != "auth_ok":
                    log.error("Auth failed: %s", ack)
                    await asyncio.sleep(RECONNECT_DELAY)
                    continue
                log.info("Connected and authenticated")

                async for raw in ws:
                    job = json.loads(raw)
                    log.info("Job %s: %s", job.get("job_id"), job.get("url"))
                    # Run in executor to avoid blocking the event loop (keeps WS alive)
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(None, _do_check, job)
                    log.info("Job %s: status=%s", job.get("job_id"), result["status_code"])
                    await ws.send(json.dumps(result))

        except (websockets.ConnectionClosed, ConnectionError, OSError) as e:
            log.warning("Connection lost (%s), reconnecting in %ds...", e, RECONNECT_DELAY)
        except Exception as e:
            log.exception("Unexpected error: %s", e)

        await asyncio.sleep(RECONNECT_DELAY)


def main():
    if not TOKEN:
        log.error("RELAY_TOKEN env var is required")
        sys.exit(1)
    asyncio.run(_run_worker())


if __name__ == "__main__":
    main()
