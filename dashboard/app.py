"""Web dashboard for viewing students and check results."""

import asyncio
import csv
import hashlib
import hmac
import io
import json
import logging
import os
import uuid
from datetime import date
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import aiosqlite
import yaml
from fastapi import FastAPI, Form, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)

_BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = os.getenv("DB_PATH", str(_BASE_DIR / "bot.db"))
SPECS_DIR = _BASE_DIR / "specs"
ACTIVE_LABS = [l.strip() for l in os.getenv("ACTIVE_LABS", "").split(",") if l.strip()]
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")

RELAY_TOKEN = os.getenv("RELAY_TOKEN", "")

COOKIE_NAME = "dash_auth"

app = FastAPI(title="Autochecker Dashboard")

# ---------------------------------------------------------------------------
# Relay state: one connected worker, pending job futures
# ---------------------------------------------------------------------------
_relay_worker: Optional[WebSocket] = None
_relay_jobs: dict[str, asyncio.Future] = {}  # job_id -> Future[dict]
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _sign_cookie(password: str) -> str:
    """Create HMAC-SHA256 signature for the auth cookie."""
    return hmac.new(password.encode(), b"authenticated", hashlib.sha256).hexdigest()


def _verify_cookie(cookie_value: str) -> bool:
    """Check that the auth cookie matches the expected signature."""
    if not DASHBOARD_PASSWORD:
        return True
    expected = _sign_cookie(DASHBOARD_PASSWORD)
    return hmac.compare_digest(cookie_value, expected)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Redirect unauthenticated requests to /login."""
    if not DASHBOARD_PASSWORD:
        return await call_next(request)

    if request.url.path in ("/login", "/login/") or request.url.path.startswith("/relay/"):
        return await call_next(request)

    cookie = request.cookies.get(COOKIE_NAME, "")
    if not _verify_cookie(cookie):
        return RedirectResponse("/login", status_code=302)

    return await call_next(request)


# ---------------------------------------------------------------------------
# Login routes
# ---------------------------------------------------------------------------

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: Optional[str] = Query(default=None)):
    """Render the login form."""
    return templates.TemplateResponse("login.html", {
        "request": request,
        "error": error,
    })


@app.post("/login")
async def login_submit(password: str = Form(...)):
    """Verify password, set auth cookie, redirect to dashboard."""
    if not hmac.compare_digest(password, DASHBOARD_PASSWORD):
        return RedirectResponse("/login?error=wrong", status_code=302)

    response = RedirectResponse("/", status_code=302)
    response.set_cookie(
        COOKIE_NAME,
        _sign_cookie(DASHBOARD_PASSWORD),
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,  # 30 days
    )
    return response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_task_metadata() -> list[dict]:
    """Load task id+title from spec files for active labs."""
    tasks: list[dict] = []
    discovered_labs = sorted(path.stem for path in SPECS_DIR.glob("lab-*.yaml"))
    lab_ids = ACTIVE_LABS + [lab for lab in discovered_labs if lab not in ACTIVE_LABS]

    for lab_id in lab_ids:
        spec_path = SPECS_DIR / f"{lab_id}.yaml"
        if not spec_path.exists():
            continue
        with open(spec_path, "r", encoding="utf-8") as f:
            spec = yaml.safe_load(f)
        for t in spec.get("tasks", []):
            tasks.append({
                "lab_id": lab_id,
                "task_id": t["id"],
                "title": t["title"],
            })
    return tasks


def _cell_status(passed: Optional[int], failed: Optional[int], total: Optional[int]) -> str:
    """Return 'pass' (100%), 'partial' (>=75%), 'fail' (<75%), or 'none'."""
    if total is None or total == 0:
        return "none"
    if failed == 0:
        return "pass"
    pct = (passed or 0) / total * 100
    if pct >= 75:
        return "partial"
    return "fail"


def _cell_pct(passed: Optional[int], total: Optional[int]) -> int:
    """Return integer percentage (0-100) for sorting. -1 if no data."""
    if total is None or total == 0:
        return -1
    return round((passed or 0) / total * 100)


async def _fetch_best_scores(db: aiosqlite.Connection) -> dict[int, dict[str, dict]]:
    """Best result per student per task (highest passed count, lowest failed).

    Returns {tg_id: {"lab:task": {"score": str, "passed": int, "failed": int, "total": int, "status": str, "pct": int}}}
    """
    scores: dict[int, dict[str, dict]] = {}
    async with db.execute("""
        SELECT tg_id, lab_id, task_id, score, passed, failed, total
        FROM results
        ORDER BY tg_id, lab_id, task_id
    """) as cur:
        async for row in cur:
            key = f"{row['lab_id']}:{row['task_id']}"
            entry = {
                "score": row["score"] or "—",
                "passed": row["passed"],
                "failed": row["failed"],
                "total": row["total"],
            }
            entry["status"] = _cell_status(entry["passed"], entry["failed"], entry["total"])
            entry["pct"] = _cell_pct(entry["passed"], entry["total"])
            prev = scores.setdefault(row["tg_id"], {}).get(key)
            if prev is None:
                scores[row["tg_id"]][key] = entry
            else:
                # Better = fewer failures; tie-break by more passes
                prev_f = prev["failed"] if prev["failed"] is not None else 999
                cur_f = entry["failed"] if entry["failed"] is not None else 999
                prev_p = prev["passed"] if prev["passed"] is not None else 0
                cur_p = entry["passed"] if entry["passed"] is not None else 0
                if (cur_f, -cur_p) < (prev_f, -prev_p):
                    scores[row["tg_id"]][key] = entry
    return scores


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, lab: Optional[str] = Query(default=None)):
    """Main page: students x tasks grid with color coding and stats."""
    task_meta = load_task_metadata()
    labs = sorted({t["lab_id"] for t in task_meta})
    active_lab = lab if lab in labs else (labs[0] if labs else None)

    # Filter tasks by selected lab
    tasks = [t for t in task_meta if t["lab_id"] == active_lab] if active_lab else task_meta

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        students = []
        async with db.execute(
            "SELECT tg_id, email, github_alias, tg_username, student_group FROM users ORDER BY github_alias"
        ) as cur:
            async for row in cur:
                students.append(dict(row))

        scores = await _fetch_best_scores(db)

        # Latest submission timestamp per student
        last_submission: dict[int, str] = {}
        async with db.execute(
            "SELECT tg_id, MAX(timestamp) AS last_ts FROM results GROUP BY tg_id"
        ) as cur:
            async for row in cur:
                last_submission[row["tg_id"]] = row["last_ts"] or ""

    # Attach last_submission to each student dict
    for s in students:
        ts = last_submission.get(s["tg_id"], "")
        s["last_submission"] = ts[:16].replace("T", " ") if ts else ""

    # Compute per-task pass rates
    task_stats = {}
    for t in tasks:
        key = f"{t['lab_id']}:{t['task_id']}"
        passed_count = sum(
            1 for s in students
            if scores.get(s["tg_id"], {}).get(key, {}).get("status") == "pass"
        )
        attempted_count = sum(
            1 for s in students
            if scores.get(s["tg_id"], {}).get(key, {}).get("status") in ("pass", "partial")
        )
        task_stats[key] = {
            "passed": passed_count,
            "attempted": attempted_count,
            "pass_rate": round(passed_count / len(students) * 100) if students else 0,
        }

    # Average completion across required tasks (excluding optional/setup), only for students who attempted
    required_keys = [
        f"{t['lab_id']}:{t['task_id']}" for t in tasks
        if not t["task_id"].startswith("optional") and t["task_id"] != "setup"
    ]
    if students and required_keys:
        completion_sum = 0
        attempted_students = 0
        for s in students:
            student_scores = scores.get(s["tg_id"], {})
            has_any = any(student_scores.get(k) for k in required_keys)
            if not has_any:
                continue
            attempted_students += 1
            passed_tasks = sum(
                1 for k in required_keys
                if student_scores.get(k, {}).get("status") == "pass"
            )
            completion_sum += passed_tasks / len(required_keys)
        avg_completion = round(completion_sum / attempted_students * 100) if attempted_students else 0
        not_started = len(students) - attempted_students
        completed_count = sum(
            1 for s in students
            if all(
                scores.get(s["tg_id"], {}).get(k, {}).get("status") == "pass"
                for k in required_keys
            )
        )
    else:
        avg_completion = 0
        attempted_students = 0
        not_started = len(students)
        completed_count = 0

    return templates.TemplateResponse("index.html", {
        "request": request,
        "students": students,
        "tasks": tasks,
        "scores": scores,
        "task_stats": task_stats,
        "labs": labs,
        "active_lab": active_lab,
        "avg_completion": avg_completion,
        "not_started": not_started,
        "completed_count": completed_count,
    })


@app.get("/student/{github_alias}", response_class=HTMLResponse)
async def student_detail(
    request: Request,
    github_alias: str,
    error: Optional[str] = Query(default=None),
    info: Optional[str] = Query(default=None),
    lab: Optional[str] = Query(default=None),
    task: Optional[str] = Query(default=None),
    count: Optional[int] = Query(default=None),
):
    """Detail page: full check history for a student."""
    task_meta = load_task_metadata()
    title_map = {f"{t['lab_id']}:{t['task_id']}": t["title"] for t in task_meta}

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(
            "SELECT tg_id, email, github_alias, tg_username, server_ip, student_group FROM users WHERE github_alias = ?",
            (github_alias,)
        ) as cur:
            student_row = await cur.fetchone()

        if not student_row:
            return HTMLResponse("<h1>Student not found</h1>", status_code=404)

        student = dict(student_row)

        results = []
        async with db.execute(
            """SELECT lab_id, task_id, score, passed, failed, total, details, timestamp
               FROM results WHERE tg_id = ? ORDER BY timestamp DESC""",
            (student["tg_id"],)
        ) as cur:
            async for row in cur:
                r = dict(row)
                key = f"{r['lab_id']}:{r['task_id']}"
                r["title"] = title_map.get(key, r["task_id"])
                r["status"] = _cell_status(r["passed"], r["failed"], r["total"])
                # Parse per-check details JSON
                r["checks"] = []
                if r.get("details"):
                    try:
                        r["checks"] = json.loads(r["details"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                results.append(r)

        latest_by_task: dict[str, dict] = {}
        for result in results:
            key = f"{result['lab_id']}:{result['task_id']}"
            if key not in latest_by_task:
                latest_by_task[key] = result

        task_attempts_map: dict[str, dict] = {}
        async with db.execute(
            """SELECT lab_id, task_id, COUNT(*) AS attempts, MAX(timestamp) AS last_attempt
               FROM attempts WHERE tg_id = ? GROUP BY lab_id, task_id
               ORDER BY lab_id, task_id""",
            (student["tg_id"],)
        ) as cur:
            async for row in cur:
                key = f"{row['lab_id']}:{row['task_id']}"
                latest = latest_by_task.get(key, {})
                task_attempts_map[key] = {
                    "lab_id": row["lab_id"],
                    "task_id": row["task_id"],
                    "title": title_map.get(key, row["task_id"]),
                    "attempts": row["attempts"] or 0,
                    "last_attempt": row["last_attempt"] or "",
                    "score": latest.get("score") or "—",
                    "status": latest.get("status", "none"),
                }

        task_attempts = sorted(
            task_attempts_map.values(),
            key=lambda row: (row["lab_id"], row["task_id"]),
        )

    return templates.TemplateResponse("student.html", {
        "request": request,
        "student": student,
        "results": results,
        "task_attempts": task_attempts,
        "error": error,
        "info": info,
        "info_lab": lab,
        "info_task": task,
        "info_count": count,
    })


@app.post("/student/{github_alias}/edit")
async def student_edit(
    github_alias: str,
    email: str = Form(...),
    new_github_alias: str = Form(..., alias="github_alias"),
    tg_username: str = Form(""),
    server_ip: str = Form(""),
):
    """Update student info. Redirects back to student page."""
    email = email.strip()
    new_github_alias = new_github_alias.strip()
    tg_username = tg_username.strip()
    server_ip = server_ip.strip()

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Find the student by current alias
        async with db.execute(
            "SELECT tg_id FROM users WHERE github_alias = ?", (github_alias,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return HTMLResponse("<h1>Student not found</h1>", status_code=404)
        tg_id = row["tg_id"]

        # Check uniqueness — email and github_alias must not belong to another student
        async with db.execute(
            "SELECT tg_id FROM users WHERE (email = ? OR github_alias = ?) AND tg_id != ?",
            (email, new_github_alias, tg_id),
        ) as cur:
            conflict = await cur.fetchone()
        if conflict:
            return RedirectResponse(
                f"/student/{github_alias}?error=conflict", status_code=302
            )

        await db.execute(
            "UPDATE users SET email = ?, github_alias = ?, tg_username = ?, server_ip = ? WHERE tg_id = ?",
            (email, new_github_alias, tg_username, server_ip, tg_id),
        )
        await db.commit()

    return RedirectResponse(f"/student/{new_github_alias}", status_code=302)


@app.post("/student/{github_alias}/attempts/reset")
async def student_reset_attempts(
    github_alias: str,
    lab_id: str = Form(...),
    task_id: str = Form(...),
):
    """Reset attempts counter for a student's specific lab task."""
    lab_id = lab_id.strip()
    task_id = task_id.strip()
    if not lab_id or not task_id:
        return RedirectResponse(f"/student/{github_alias}", status_code=302)

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(
            "SELECT tg_id FROM users WHERE github_alias = ?", (github_alias,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return HTMLResponse("<h1>Student not found</h1>", status_code=404)
        tg_id = row["tg_id"]

        async with db.execute(
            "SELECT COUNT(*) AS cnt FROM attempts WHERE tg_id = ? AND lab_id = ? AND task_id = ?",
            (tg_id, lab_id, task_id),
        ) as cur:
            count_row = await cur.fetchone()
        deleted_count = int(count_row["cnt"]) if count_row else 0

        await db.execute(
            "DELETE FROM attempts WHERE tg_id = ? AND lab_id = ? AND task_id = ?",
            (tg_id, lab_id, task_id),
        )
        await db.commit()

    query = urlencode({
        "info": "attempts_reset",
        "lab": lab_id,
        "task": task_id,
        "count": deleted_count,
    })
    return RedirectResponse(f"/student/{github_alias}?{query}", status_code=302)


@app.get("/export/csv")
async def export_csv(lab: Optional[str] = Query(default=None)):
    """Download CSV with best scores per student per task."""
    task_meta = load_task_metadata()
    labs = sorted({t["lab_id"] for t in task_meta})
    active_lab = lab if lab in labs else (labs[0] if labs else None)
    tasks = [t for t in task_meta if t["lab_id"] == active_lab] if active_lab else task_meta

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        students = []
        async with db.execute(
            "SELECT tg_id, email, github_alias, student_group FROM users ORDER BY github_alias"
        ) as cur:
            async for row in cur:
                students.append(dict(row))

        scores = await _fetch_best_scores(db)

    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    header = ["github_alias", "email", "group"]
    for t in tasks:
        header.append(t["task_id"])
    writer.writerow(header)

    # Rows
    for s in students:
        row = [s["github_alias"], s["email"], s.get("student_group", "")]
        for t in tasks:
            key = f"{t['lab_id']}:{t['task_id']}"
            entry = scores.get(s["tg_id"], {}).get(key)
            if entry:
                row.append(entry["score"])
            else:
                row.append("")
        writer.writerow(row)

    output.seek(0)
    filename = f"autochecker-{active_lab or 'all'}-{date.today().isoformat()}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Relay: WebSocket for worker + HTTP for engine
# ---------------------------------------------------------------------------

@app.websocket("/relay/ws")
async def relay_worker_ws(ws: WebSocket):
    """WebSocket endpoint for the university VM relay worker."""
    global _relay_worker

    await ws.accept()

    # First message must be auth
    try:
        raw = await asyncio.wait_for(ws.receive_text(), timeout=10)
        msg = json.loads(raw)
    except Exception:
        await ws.close(code=4001, reason="Auth timeout")
        return

    if not RELAY_TOKEN or msg.get("type") != "auth" or not hmac.compare_digest(msg.get("token", ""), RELAY_TOKEN):
        await ws.send_json({"type": "auth_fail"})
        await ws.close(code=4003, reason="Invalid token")
        return

    await ws.send_json({"type": "auth_ok"})
    _relay_worker = ws
    logger.info("Relay worker connected")

    try:
        while True:
            raw = await ws.receive_text()
            result = json.loads(raw)
            job_id = result.get("job_id")
            fut = _relay_jobs.pop(job_id, None)
            if fut and not fut.done():
                fut.set_result(result)
    except WebSocketDisconnect:
        logger.info("Relay worker disconnected")
    except Exception as e:
        logger.warning("Relay worker error: %s", e)
    finally:
        if _relay_worker is ws:
            _relay_worker = None


async def _await_worker(timeout: float = 12) -> bool:
    """Wait for the relay worker to (re)connect. Returns True if available."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if _relay_worker is not None:
            return True
        await asyncio.sleep(1)
    return False


async def _send_relay_job(job: dict, timeout: int) -> JSONResponse:
    """Send a job to the relay worker with automatic retry on stale connections.

    Handles the case where the university network kills the WebSocket:
    detects stale connections, clears the worker reference, waits for
    reconnection, and retries.
    """
    global _relay_worker

    for attempt in range(3):
        if _relay_worker is None:
            if not await _await_worker(timeout=15):
                return JSONResponse({"error": "no worker connected", "job_id": job.get("job_id", ""),
                                     "status_code": 0, "exit_code": -1}, status_code=503)

        job_id = uuid.uuid4().hex[:12]
        job["job_id"] = job_id
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        _relay_jobs[job_id] = fut

        try:
            await _relay_worker.send_json(job)
            result = await asyncio.wait_for(fut, timeout=timeout + 15)
            return JSONResponse(result)
        except asyncio.TimeoutError:
            _relay_jobs.pop(job_id, None)
            if attempt < 2:
                logger.warning("Relay job %s timed out (attempt %d), marking worker stale...", job_id, attempt + 1)
                _relay_worker = None  # Force reconnection wait
                continue
            return JSONResponse({"error": "worker timeout", "job_id": job_id,
                                 "status_code": 0, "exit_code": -1}, status_code=504)
        except Exception as e:
            _relay_jobs.pop(job_id, None)
            logger.warning("Relay send failed (attempt %d): %s", attempt + 1, e)
            _relay_worker = None  # Connection is stale, force reconnection
            if attempt < 2:
                continue
            return JSONResponse({"error": "worker connection lost", "job_id": job_id,
                                 "status_code": 0, "exit_code": -1}, status_code=502)

    return JSONResponse({"error": "relay failed", "status_code": 0, "exit_code": -1}, status_code=502)


@app.post("/relay/check")
async def relay_check(request: Request):
    """Submit an HTTP check job to the relay worker. Called by the engine."""
    auth = request.headers.get("Authorization", "")
    if not RELAY_TOKEN or not hmac.compare_digest(auth, f"Bearer {RELAY_TOKEN}"):
        return JSONResponse({"error": "unauthorized"}, status_code=403)

    body = await request.json()
    return await _send_relay_job({
        "url": body.get("url", ""),
        "timeout": min(body.get("timeout", 10), 30),
    }, timeout=min(body.get("timeout", 10), 30))


@app.post("/relay/ssh")
async def relay_ssh(request: Request):
    """Submit an SSH check job to the relay worker. Called by the engine."""
    auth = request.headers.get("Authorization", "")
    if not RELAY_TOKEN or not hmac.compare_digest(auth, f"Bearer {RELAY_TOKEN}"):
        return JSONResponse({"error": "unauthorized"}, status_code=403)

    body = await request.json()
    timeout = min(body.get("timeout", 10), 30)
    return await _send_relay_job({
        "type": "ssh",
        "host": body.get("host", ""),
        "port": body.get("port", 22),
        "username": body.get("username", "autochecker"),
        "command": body.get("command", "echo ok"),
        "timeout": timeout,
    }, timeout=timeout)


@app.get("/relay/status")
async def relay_status(request: Request):
    """Check if a relay worker is connected."""
    auth = request.headers.get("Authorization", "")
    if not RELAY_TOKEN or not hmac.compare_digest(auth, f"Bearer {RELAY_TOKEN}"):
        return JSONResponse({"error": "unauthorized"}, status_code=403)
    return JSONResponse({"worker_connected": _relay_worker is not None})
