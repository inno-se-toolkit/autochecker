"""Handler for task check callbacks."""

import asyncio
import functools
import json
import os
import re

import requests

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from ..database import User, get_attempts_count, add_attempt, save_result, get_server_ip, get_server_ip_owner, set_server_ip, get_lms_api_key, set_lms_api_key, get_vm_username, set_vm_username
from ..ip_utils import validate_ip
from ..keyboards import get_labs_keyboard, get_tasks_keyboard
from ..runner import run_check
from ..config import MAX_ATTEMPTS_PER_TASK, ACTIVE_LABS, get_max_attempts, get_tasks_needing_ip, get_tasks_needing_lms_key, get_tasks_needing_vm_username

router = Router()


AUTOCHECKER_PUBKEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKiL0DDQZw7L0Uf1c9cNlREY7IS6ZkIbGVWNsClqGNCZ se-toolkit-autochecker"


def _check_vm_reachable_sync(ip: str) -> tuple[bool, str]:
    """Check if a VM is reachable via SSH through the relay (blocking)."""
    relay_url = os.environ.get("RELAY_URL", "http://dashboard:8000/relay/ssh")
    relay_token = os.environ.get("RELAY_TOKEN", "")
    if not relay_token:
        return True, ""  # skip check if relay not configured
    try:
        resp = requests.post(
            relay_url,
            json={"host": ip, "port": 22, "username": "root",
                  "command": "echo ok", "timeout": 5},
            headers={"Authorization": f"Bearer {relay_token}"},
            timeout=15,
        )
        if resp.status_code == 503:
            return True, ""  # relay worker offline, skip check
        if resp.status_code != 200:
            return False, f"Relay error: {resp.status_code}"
        data = resp.json()
        # SSH connect succeeded (even if auth fails, the VM is reachable)
        if data.get("error") == "timeout":
            return False, "Connection timed out — VM may be down or unreachable."
        return True, ""
    except requests.Timeout:
        return False, "Connection timed out — VM may be down or unreachable."
    except Exception as e:
        return True, ""  # on unexpected errors, don't block the student


async def _check_vm_reachable(ip: str) -> tuple[bool, str]:
    """Async wrapper for VM reachability check."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, functools.partial(_check_vm_reachable_sync, ip)
    )


class CheckStates(StatesGroup):
    waiting_for_server_ip = State()
    waiting_for_vm_username = State()
    waiting_for_lms_key = State()

BLOCK_TAG_RE = re.compile(r"<(/?(h[1-6]|p|div|br|li|ul|ol|tr|hr)[^>]*)>", re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")


def _parse_summary_html(path) -> str | None:
    """Extract plain text from summary.html, preserving line breaks."""
    try:
        html = path.read_text(encoding="utf-8")
        # Add newline before block-level tags
        text = BLOCK_TAG_RE.sub(r"\n", html)
        text = TAG_RE.sub("", text)
        # Collapse multiple blank lines
        lines = [line.strip() for line in text.splitlines()]
        return "\n".join(line for line in lines if line) or None
    except Exception:
        return None


@router.message(Command("reset"))
async def cmd_reset(message: Message, db_user: User, state: FSMContext) -> None:
    """Show reset options for stored settings."""
    if db_user is None:
        await message.answer("Please /start to register first.")
        return

    await state.clear()

    any_lab_needs_lms = any(get_tasks_needing_lms_key(lab) for lab in ACTIVE_LABS)

    server_ip = await get_server_ip(db_user.tg_id)
    vm_user = await get_vm_username(db_user.tg_id)
    lms_key = await get_lms_api_key(db_user.tg_id) if any_lab_needs_lms else ""

    lines = ["<b>Your stored settings:</b>\n"]
    buttons = []

    if server_ip:
        lines.append(f"VM IP: <code>{server_ip}</code>")
        buttons.append([InlineKeyboardButton(text="Reset VM IP", callback_data="reset:server_ip")])
    else:
        lines.append("VM IP: <i>not set</i>")

    if vm_user:
        lines.append(f"VM username: <code>{vm_user}</code>")
        buttons.append([InlineKeyboardButton(text="Reset VM username", callback_data="reset:vm_username")])
    else:
        lines.append("VM username: <i>not set</i>")

    if any_lab_needs_lms:
        if lms_key:
            lines.append(f"LMS API key: <code>{lms_key[:6]}...</code>")
            buttons.append([InlineKeyboardButton(text="Reset LMS API key", callback_data="reset:lms_api_key")])
        else:
            lines.append("LMS API key: <i>not set</i>")

    if not buttons:
        lines.append("\nNothing to reset.")

    await message.answer(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None,
    )


@router.callback_query(F.data.startswith("reset:"))
async def callback_reset(callback: CallbackQuery, db_user: User) -> None:
    """Handle reset button press."""
    field = callback.data.split(":", 1)[1]

    if field == "server_ip":
        await set_server_ip(db_user.tg_id, "")
        await callback.answer("VM IP reset. You'll be asked again on next check.", show_alert=True)
    elif field == "vm_username":
        await set_vm_username(db_user.tg_id, "")
        await callback.answer("VM username reset. You'll be asked again on next check.", show_alert=True)
    elif field == "lms_api_key":
        await set_lms_api_key(db_user.tg_id, "")
        await callback.answer("LMS API key reset. You'll be asked again on next check.", show_alert=True)
    else:
        await callback.answer("Unknown setting.", show_alert=True)
        return

    any_lab_needs_lms = any(get_tasks_needing_lms_key(lab) for lab in ACTIVE_LABS)

    # Refresh the message
    server_ip = await get_server_ip(db_user.tg_id)
    vm_user = await get_vm_username(db_user.tg_id)
    lms_key = await get_lms_api_key(db_user.tg_id) if any_lab_needs_lms else ""

    lines = ["<b>Your stored settings:</b>\n"]
    buttons = []

    if server_ip:
        lines.append(f"VM IP: <code>{server_ip}</code>")
        buttons.append([InlineKeyboardButton(text="Reset VM IP", callback_data="reset:server_ip")])
    else:
        lines.append("VM IP: <i>not set</i>")

    if vm_user:
        lines.append(f"VM username: <code>{vm_user}</code>")
        buttons.append([InlineKeyboardButton(text="Reset VM username", callback_data="reset:vm_username")])
    else:
        lines.append("VM username: <i>not set</i>")

    if any_lab_needs_lms:
        if lms_key:
            lines.append(f"LMS API key: <code>{lms_key[:6]}...</code>")
            buttons.append([InlineKeyboardButton(text="Reset LMS API key", callback_data="reset:lms_api_key")])
        else:
            lines.append("LMS API key: <i>not set</i>")

    if not buttons:
        lines.append("\nAll settings cleared.")

    try:
        await callback.message.edit_text(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None,
        )
    except TelegramBadRequest:
        pass


@router.callback_query(F.data.startswith("locked:"))
async def callback_locked(callback: CallbackQuery) -> None:
    """Handle click on a locked task."""
    prereq = callback.data.split(":", 1)[1]
    await callback.answer(f"Pass \"{prereq}\" first.", show_alert=True)


@router.callback_query(F.data.startswith("check:"))
async def callback_check_task(callback: CallbackQuery, db_user: User, state: FSMContext) -> None:
    """Handle task selection — run check immediately."""
    if db_user is None:
        await callback.answer("Please /start to register first.", show_alert=True)
        return

    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Invalid task selection", show_alert=True)
        return

    lab_id = parts[1]
    task_id = parts[2]

    max_attempts = get_max_attempts(lab_id, task_id)
    attempts = await get_attempts_count(db_user.tg_id, lab_id, task_id)
    if attempts >= max_attempts:
        await callback.answer(
            f"No attempts left for {task_id}.",
            show_alert=True
        )
        return

    # For tasks needing a server IP, check if we have one stored
    # agent_eval tasks also need server_ip (SSH to student VM)
    server_ip = ""
    if task_id in get_tasks_needing_ip(lab_id) or task_id in get_tasks_needing_lms_key(lab_id):
        server_ip = await get_server_ip(db_user.tg_id)
        if not server_ip:
            await callback.answer()
            await callback.message.edit_text(
                f"To check <b>{task_id}</b>, I need your VM's IP address.\n\n"
                f"Reply with your VM IP (e.g., <code>10.90.138.42</code>):",
            )
            await state.set_state(CheckStates.waiting_for_server_ip)
            await state.update_data(lab_id=lab_id, task_id=task_id)
            return

    # For tasks needing VM username (agent_eval or __vm_username__ ssh_checks)
    vm_username = ""
    lms_api_key = ""
    if task_id in get_tasks_needing_vm_username(lab_id):
        vm_username = await get_vm_username(db_user.tg_id)
        if not vm_username:
            await callback.answer()
            await callback.message.edit_text(
                f"To check <b>{task_id}</b>, I need your VM username.\n\n"
                f"The autochecker will SSH into your VM to run checks. "
                f"Run this on your VM:\n\n"
                f"<code>whoami</code>\n\n"
                f"Reply with the output:",
            )
            await state.set_state(CheckStates.waiting_for_vm_username)
            await state.update_data(lab_id=lab_id, task_id=task_id)
            return

    # For agent_eval tasks, also need LMS API key
    if task_id in get_tasks_needing_lms_key(lab_id):
        lms_api_key = await get_lms_api_key(db_user.tg_id)
        if not lms_api_key:
            await callback.answer()
            await callback.message.edit_text(
                f"To check <b>{task_id}</b>, I need your <code>LMS_API_KEY</code> "
                f"(the backend API key from your <code>.env.docker.secret</code>).\n\n"
                f"Reply with your LMS_API_KEY:",
            )
            await state.set_state(CheckStates.waiting_for_lms_key)
            await state.update_data(lab_id=lab_id, task_id=task_id)
            return

    await callback.answer()

    has_eval = bool(get_tasks_needing_lms_key(lab_id) & {task_id})
    time_est = "a few minutes" if has_eval else "60 seconds"
    await callback.message.edit_text(
        f"Checking <b>{task_id}</b>...\n\n"
        f"This may take up to {time_est}.",
    )

    # Run the check using github_alias
    result = await run_check(db_user.github_alias, lab_id, task_id, server_ip=server_ip or None, lms_api_key=lms_api_key or None, vm_username=vm_username or None)

    # Record the attempt
    await add_attempt(db_user.tg_id, lab_id, task_id)

    # Parse score details and per-check breakdown from results JSON
    passed = None
    failed = None
    total = None
    details_json = ""
    if result.results_json_path and result.results_json_path.exists():
        try:
            with open(result.results_json_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if lines:
                data = json.loads(lines[0].strip())
                passed = data.get("passed_checks")
                failed = data.get("failed_checks")
                total = data.get("total_checks")
            # Lines 2+ are individual check results
            checks = []
            for line in lines[1:]:
                line = line.strip()
                if line:
                    checks.append(json.loads(line))
            if checks:
                details_json = json.dumps(checks, ensure_ascii=False)
        except (json.JSONDecodeError, IOError):
            pass

    # Save result to DB
    await save_result(
        tg_id=db_user.tg_id,
        lab_id=lab_id,
        task_id=task_id,
        score=result.score,
        passed=passed,
        failed=failed,
        total=total,
        details=details_json,
    )

    # Handle runner-level error (timeout, script not found)
    if result.error_message:
        await callback.message.edit_text(
            result.error_message,
            reply_markup=await get_tasks_keyboard(db_user.tg_id, lab_id)
        )
        return

    # Build result message
    if result.score:
        status_emoji = "✅" if (failed is not None and failed == 0) else "⚠️"
        score_text = f"\nScore: <b>{result.score}</b>"
    else:
        status_emoji = "⚠️"
        score_text = ""

    await callback.message.edit_text(
        f"{status_emoji} Check complete for <b>{task_id}</b>!{score_text}\n\n"
        f"Attempts used: {attempts + 1}/{max_attempts}",
    )

    # Send feedback to student
    if result.student_report_path and result.student_report_path.exists():
        # student_report.txt — clean, student-friendly, failures only
        try:
            report_text = result.student_report_path.read_text(encoding="utf-8")
            if len(report_text) <= 4000:
                await callback.message.answer(
                    f"<pre>{report_text}</pre>",
                )
            else:
                await callback.message.answer_document(
                    FSInputFile(result.student_report_path, filename="report.txt"),
                    caption=f"Report for {task_id}"
                )
        except (TelegramBadRequest, Exception):
            try:
                await callback.message.answer_document(
                    FSInputFile(result.student_report_path, filename="report.txt"),
                    caption=f"Report for {task_id}"
                )
            except TelegramBadRequest:
                pass
    elif result.summary_html_path and result.summary_html_path.exists():
        # Fallback: parse summary.html for a short message
        summary = _parse_summary_html(result.summary_html_path)
        if summary:
            await callback.message.answer(summary)
    elif not result.score:
        # No results at all — generic message
        await callback.message.answer("No results were generated. Check your repository setup.")

    # Show tasks menu again
    await callback.message.answer(
        "Choose a task:",
        reply_markup=await get_tasks_keyboard(db_user.tg_id, lab_id)
    )


@router.message(CheckStates.waiting_for_server_ip)
async def process_server_ip(message: Message, db_user: User, state: FSMContext) -> None:
    """Handle server IP input, save it, and run the check."""
    text = message.text.strip() if message.text else ""

    if text.startswith("/"):
        await state.clear()
        server_ip = await get_server_ip(db_user.tg_id)
        await message.answer(
            "Cancelled.\n\nChoose a lab:",
            reply_markup=get_labs_keyboard(server_ip=server_ip),
        )
        return

    valid, error_msg = validate_ip(text)
    if not valid:
        await message.answer(error_msg)
        return

    # Reachability check for internal IPs via relay
    if text.startswith("10."):
        checking_msg = await message.answer(f"Checking if <code>{text}</code> is reachable...")
        reachable, reach_err = await _check_vm_reachable(text)
        try:
            await checking_msg.delete()
        except TelegramBadRequest:
            pass
        if not reachable:
            await message.answer(
                f"VM <code>{text}</code> is not reachable.\n\n"
                f"{reach_err}\n\n"
                "Please check that:\n"
                "1. Your VM is running\n"
                "2. The IP is correct\n"
                "3. SSH is enabled on the VM\n\n"
                "Enter your VM IP:"
            )
            return

    # Check uniqueness — each student must have their own VM IP
    existing_owner = await get_server_ip_owner(text, db_user.tg_id)
    if existing_owner:
        await message.answer(
            f"This IP is already registered to another student.\n"
            f"Each student must use their own VM. Please enter your unique VM IP:"
        )
        return

    # Save IP and clear FSM state
    await set_server_ip(db_user.tg_id, text)
    data = await state.get_data()
    await state.clear()

    lab_id = data["lab_id"]
    task_id = data["task_id"]

    max_attempts = get_max_attempts(lab_id, task_id)
    attempts = await get_attempts_count(db_user.tg_id, lab_id, task_id)
    if attempts >= max_attempts:
        await message.answer(f"No attempts left for {task_id}.")
        return

    status_msg = await message.answer(
        f"Saved VM IP: <code>{text}</code>\n\n"
        f"Checking <b>{task_id}</b>...\n"
        f"This may take up to 60 seconds.",
    )

    result = await run_check(db_user.github_alias, lab_id, task_id, server_ip=text)

    # Record the attempt
    await add_attempt(db_user.tg_id, lab_id, task_id)

    # Parse score details
    passed = None
    failed = None
    total = None
    details_json = ""
    if result.results_json_path and result.results_json_path.exists():
        try:
            with open(result.results_json_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if lines:
                score_data = json.loads(lines[0].strip())
                passed = score_data.get("passed_checks")
                failed = score_data.get("failed_checks")
                total = score_data.get("total_checks")
            checks = []
            for line in lines[1:]:
                line = line.strip()
                if line:
                    checks.append(json.loads(line))
            if checks:
                details_json = json.dumps(checks, ensure_ascii=False)
        except (json.JSONDecodeError, IOError):
            pass

    await save_result(
        tg_id=db_user.tg_id, lab_id=lab_id, task_id=task_id,
        score=result.score, passed=passed, failed=failed, total=total, details=details_json,
    )

    if result.error_message:
        await status_msg.edit_text(
            result.error_message,
            reply_markup=await get_tasks_keyboard(db_user.tg_id, lab_id)
        )
        return

    if result.score:
        status_emoji = "✅" if (failed is not None and failed == 0) else "⚠️"
        score_text = f"\nScore: <b>{result.score}</b>"
    else:
        status_emoji = "⚠️"
        score_text = ""

    await status_msg.edit_text(
        f"{status_emoji} Check complete for <b>{task_id}</b>!{score_text}\n\n"
        f"Attempts used: {attempts + 1}/{max_attempts}",
    )

    if result.student_report_path and result.student_report_path.exists():
        try:
            report_text = result.student_report_path.read_text(encoding="utf-8")
            if len(report_text) <= 4000:
                await message.answer(f"<pre>{report_text}</pre>")
            else:
                await message.answer_document(
                    FSInputFile(result.student_report_path, filename="report.txt"),
                    caption=f"Report for {task_id}"
                )
        except (TelegramBadRequest, Exception):
            try:
                await message.answer_document(
                    FSInputFile(result.student_report_path, filename="report.txt"),
                    caption=f"Report for {task_id}"
                )
            except TelegramBadRequest:
                pass
    elif result.summary_html_path and result.summary_html_path.exists():
        summary = _parse_summary_html(result.summary_html_path)
        if summary:
            await message.answer(summary)
    elif not result.score:
        await message.answer("No results were generated. Check your repository setup.")

    await message.answer(
        "Choose a task:",
        reply_markup=await get_tasks_keyboard(db_user.tg_id, lab_id)
    )


@router.message(CheckStates.waiting_for_vm_username)
async def process_vm_username(message: Message, db_user: User, state: FSMContext) -> None:
    """Handle VM username input, save it, then ask for LMS_API_KEY."""
    text = message.text.strip() if message.text else ""

    if text.startswith("/"):
        await state.clear()
        server_ip = await get_server_ip(db_user.tg_id)
        await message.answer(
            "Cancelled.\n\nChoose a lab:",
            reply_markup=get_labs_keyboard(server_ip=server_ip),
        )
        return

    # Validate: alphanumeric, underscore, hyphen, 1-32 chars
    if not text or not re.match(r'^[a-zA-Z0-9_-]{1,32}$', text):
        await message.answer(
            "Invalid username. Must be 1-32 characters (letters, digits, underscore, hyphen).\n"
            "Run <code>whoami</code> on your VM to check. Try again:"
        )
        return

    await set_vm_username(db_user.tg_id, text)
    data = await state.get_data()

    lab_id = data["lab_id"]
    task_id = data["task_id"]

    # Now check if we also need LMS_API_KEY
    lms_api_key = await get_lms_api_key(db_user.tg_id)
    if not lms_api_key:
        await state.update_data(lab_id=lab_id, task_id=task_id)
        await state.set_state(CheckStates.waiting_for_lms_key)
        await message.answer(
            f"Saved VM username: <code>{text}</code>\n\n"
            f"Now I need your <code>LMS_API_KEY</code> "
            f"(the backend API key from your <code>.env.docker.secret</code>).\n\n"
            f"Reply with your LMS_API_KEY:",
        )
        return

    await state.clear()

    max_attempts = get_max_attempts(lab_id, task_id)
    attempts = await get_attempts_count(db_user.tg_id, lab_id, task_id)
    if attempts >= max_attempts:
        await message.answer(f"No attempts left for {task_id}.")
        return

    server_ip = await get_server_ip(db_user.tg_id)

    status_msg = await message.answer(
        f"Saved VM username: <code>{text}</code>\n\n"
        f"Checking <b>{task_id}</b>...\n"
        f"This may take a few minutes.",
    )

    result = await run_check(db_user.github_alias, lab_id, task_id, server_ip=server_ip or None, lms_api_key=lms_api_key or None, vm_username=text)

    await add_attempt(db_user.tg_id, lab_id, task_id)

    passed = None
    failed = None
    total = None
    details_json = ""
    if result.results_json_path and result.results_json_path.exists():
        try:
            with open(result.results_json_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if lines:
                score_data = json.loads(lines[0].strip())
                passed = score_data.get("passed_checks")
                failed = score_data.get("failed_checks")
                total = score_data.get("total_checks")
            checks = []
            for line in lines[1:]:
                line = line.strip()
                if line:
                    checks.append(json.loads(line))
            if checks:
                details_json = json.dumps(checks, ensure_ascii=False)
        except (json.JSONDecodeError, IOError):
            pass

    await save_result(
        tg_id=db_user.tg_id, lab_id=lab_id, task_id=task_id,
        score=result.score, passed=passed, failed=failed, total=total, details=details_json,
    )

    if result.error_message:
        await status_msg.edit_text(
            result.error_message,
            reply_markup=await get_tasks_keyboard(db_user.tg_id, lab_id)
        )
        return

    if result.score:
        status_emoji = "✅" if (failed is not None and failed == 0) else "⚠️"
        score_text = f"\nScore: <b>{result.score}</b>"
    else:
        status_emoji = "⚠️"
        score_text = ""

    await status_msg.edit_text(
        f"{status_emoji} Check complete for <b>{task_id}</b>!{score_text}\n\n"
        f"Attempts used: {attempts + 1}/{max_attempts}",
    )

    if result.student_report_path and result.student_report_path.exists():
        try:
            report_text = result.student_report_path.read_text(encoding="utf-8")
            if len(report_text) <= 4000:
                await message.answer(f"<pre>{report_text}</pre>")
            else:
                await message.answer_document(
                    FSInputFile(result.student_report_path, filename="report.txt"),
                    caption=f"Report for {task_id}"
                )
        except (TelegramBadRequest, Exception):
            try:
                await message.answer_document(
                    FSInputFile(result.student_report_path, filename="report.txt"),
                    caption=f"Report for {task_id}"
                )
            except TelegramBadRequest:
                pass
    elif result.summary_html_path and result.summary_html_path.exists():
        summary = _parse_summary_html(result.summary_html_path)
        if summary:
            await message.answer(summary)
    elif not result.score:
        await message.answer("No results were generated. Check your repository setup.")

    await message.answer(
        "Choose a task:",
        reply_markup=await get_tasks_keyboard(db_user.tg_id, lab_id)
    )


@router.message(CheckStates.waiting_for_lms_key)
async def process_lms_key(message: Message, db_user: User, state: FSMContext) -> None:
    """Handle LMS API key input, save it, and run the check."""
    text = message.text.strip() if message.text else ""

    if text.startswith("/"):
        await state.clear()
        server_ip = await get_server_ip(db_user.tg_id)
        await message.answer(
            "Cancelled.\n\nChoose a lab:",
            reply_markup=get_labs_keyboard(server_ip=server_ip),
        )
        return

    if not text or len(text) < 3:
        await message.answer("LMS_API_KEY must be at least 3 characters. Try again:")
        return

    await set_lms_api_key(db_user.tg_id, text)
    data = await state.get_data()
    await state.clear()

    lab_id = data["lab_id"]
    task_id = data["task_id"]

    max_attempts = get_max_attempts(lab_id, task_id)
    attempts = await get_attempts_count(db_user.tg_id, lab_id, task_id)
    if attempts >= max_attempts:
        await message.answer(f"No attempts left for {task_id}.")
        return

    server_ip = await get_server_ip(db_user.tg_id)
    vm_username = await get_vm_username(db_user.tg_id)

    status_msg = await message.answer(
        f"Saved LMS_API_KEY.\n\n"
        f"Checking <b>{task_id}</b>...\n"
        f"This may take a few minutes.",
    )

    result = await run_check(db_user.github_alias, lab_id, task_id, server_ip=server_ip or None, lms_api_key=text, vm_username=vm_username or None)

    await add_attempt(db_user.tg_id, lab_id, task_id)

    passed = None
    failed = None
    total = None
    details_json = ""
    if result.results_json_path and result.results_json_path.exists():
        try:
            with open(result.results_json_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if lines:
                score_data = json.loads(lines[0].strip())
                passed = score_data.get("passed_checks")
                failed = score_data.get("failed_checks")
                total = score_data.get("total_checks")
            checks = []
            for line in lines[1:]:
                line = line.strip()
                if line:
                    checks.append(json.loads(line))
            if checks:
                details_json = json.dumps(checks, ensure_ascii=False)
        except (json.JSONDecodeError, IOError):
            pass

    await save_result(
        tg_id=db_user.tg_id, lab_id=lab_id, task_id=task_id,
        score=result.score, passed=passed, failed=failed, total=total, details=details_json,
    )

    if result.error_message:
        await status_msg.edit_text(
            result.error_message,
            reply_markup=await get_tasks_keyboard(db_user.tg_id, lab_id)
        )
        return

    if result.score:
        status_emoji = "✅" if (failed is not None and failed == 0) else "⚠️"
        score_text = f"\nScore: <b>{result.score}</b>"
    else:
        status_emoji = "⚠️"
        score_text = ""

    await status_msg.edit_text(
        f"{status_emoji} Check complete for <b>{task_id}</b>!{score_text}\n\n"
        f"Attempts used: {attempts + 1}/{max_attempts}",
    )

    if result.student_report_path and result.student_report_path.exists():
        try:
            report_text = result.student_report_path.read_text(encoding="utf-8")
            if len(report_text) <= 4000:
                await message.answer(f"<pre>{report_text}</pre>")
            else:
                await message.answer_document(
                    FSInputFile(result.student_report_path, filename="report.txt"),
                    caption=f"Report for {task_id}"
                )
        except (TelegramBadRequest, Exception):
            try:
                await message.answer_document(
                    FSInputFile(result.student_report_path, filename="report.txt"),
                    caption=f"Report for {task_id}"
                )
            except TelegramBadRequest:
                pass
    elif result.summary_html_path and result.summary_html_path.exists():
        summary = _parse_summary_html(result.summary_html_path)
        if summary:
            await message.answer(summary)
    elif not result.score:
        await message.answer("No results were generated. Check your repository setup.")

    await message.answer(
        "Choose a task:",
        reply_markup=await get_tasks_keyboard(db_user.tg_id, lab_id)
    )
