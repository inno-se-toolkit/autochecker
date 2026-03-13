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


_INTERNAL_IP_RE = re.compile(
    r"^(10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3})$"
)

SSH_KEY_PATH = os.path.expanduser(
    os.environ.get("SSH_KEY_PATH", "~/.ssh/autochecker_ed25519")
)


def _is_allowed_host(host: str) -> bool:
    return bool(_INTERNAL_IP_RE.match(host))


def _do_ssh_check(job: dict) -> dict:
    """Execute an SSH command on a remote host and return the result."""
    job_id = job["job_id"]
    host = job.get("host", "")
    port = job.get("port", 22)
    username = job.get("username", "autochecker")
    command = job.get("command", "echo ok")
    timeout = min(job.get("timeout", 10), 120)

    if not _is_allowed_host(host):
        return {"job_id": job_id, "exit_code": -1, "stdout": "", "stderr": "", "error": f"Host not allowed: {host}"}

    if not os.path.exists(SSH_KEY_PATH):
        return {"job_id": job_id, "exit_code": -1, "stdout": "", "stderr": "", "error": f"SSH key not found: {SSH_KEY_PATH}"}

    try:
        result = subprocess.run(
            [
                "ssh",
                "-i", SSH_KEY_PATH,
                "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                "-o", f"ConnectTimeout={timeout}",
                "-o", "LogLevel=ERROR",
                "-p", str(port),
                f"{username}@{host}",
                command,
            ],
            capture_output=True, text=True, timeout=timeout + 5,
        )
        return {
            "job_id": job_id,
            "exit_code": result.returncode,
            "stdout": result.stdout[:65536],
            "stderr": result.stderr[:4096],
            "error": "",
        }
    except subprocess.TimeoutExpired:
        return {"job_id": job_id, "exit_code": -1, "stdout": "", "stderr": "", "error": "timeout"}
    except Exception as e:
        return {"job_id": job_id, "exit_code": -1, "stdout": "", "stderr": "", "error": str(e)}


def _do_check(job: dict) -> dict:
    """Execute an HTTP check via curl and return the result.

    Supports optional method and headers for richer HTTP checks
    (e.g., agent eval proxy needs GET/POST with Authorization headers).
    """
    job_id = job["job_id"]
    url = job.get("url", "")
    method = job.get("method", "GET").upper()
    headers = job.get("headers", {})
    request_body = job.get("body")
    timeout = min(job.get("timeout", 10), 120)  # cap at 30s

    if not _is_allowed_url(url):
        return {"job_id": job_id, "status_code": 0, "body": "", "error": f"URL not allowed: {url}"}

    try:
        cmd = ["curl", "-s", "-w", "\n%{http_code}", "--connect-timeout", str(timeout)]
        if method != "GET":
            cmd += ["-X", method]
        for key, value in headers.items():
            # Skip hop-by-hop headers
            if key.lower() in ("host", "transfer-encoding", "connection"):
                continue
            cmd += ["-H", f"{key}: {value}"]
        if request_body is not None:
            cmd += ["-d", request_body]
        cmd.append(url)

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout + 5,
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
                SERVER, close_timeout=5, ping_interval=10, ping_timeout=10,
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
                    job_type = job.get("type", "http")
                    loop = asyncio.get_event_loop()

                    if job_type == "ssh":
                        log.info("SSH job %s: %s@%s", job.get("job_id"), job.get("username", "autochecker"), job.get("host"))
                        result = await loop.run_in_executor(None, _do_ssh_check, job)
                        log.info("SSH job %s: exit=%s", job.get("job_id"), result["exit_code"])
                    else:
                        log.info("HTTP job %s: %s", job.get("job_id"), job.get("url"))
                        result = await loop.run_in_executor(None, _do_check, job)
                        log.info("HTTP job %s: status=%s", job.get("job_id"), result["status_code"])

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
