"""Handler for task check callbacks."""

import json
import re

from aiogram import Router, F
from aiogram.types import CallbackQuery, FSInputFile
from aiogram.exceptions import TelegramBadRequest

from ..database import User, get_attempts_count, add_attempt, save_result
from ..keyboards import get_tasks_keyboard
from ..runner import run_check
from ..config import MAX_ATTEMPTS_PER_TASK

router = Router()

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


@router.callback_query(F.data.startswith("locked:"))
async def callback_locked(callback: CallbackQuery) -> None:
    """Handle click on a locked task."""
    prereq = callback.data.split(":", 1)[1]
    await callback.answer(f"Pass \"{prereq}\" first.", show_alert=True)


@router.callback_query(F.data.startswith("check:"))
async def callback_check_task(callback: CallbackQuery, db_user: User) -> None:
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

    attempts = await get_attempts_count(db_user.tg_id, lab_id, task_id)
    if attempts >= MAX_ATTEMPTS_PER_TASK:
        await callback.answer(
            f"No attempts left for {task_id}.",
            show_alert=True
        )
        return

    await callback.answer()

    await callback.message.edit_text(
        f"Checking <b>{task_id}</b>...\n\n"
        f"This may take up to 60 seconds.",
    )

    # Run the check using github_alias
    result = await run_check(db_user.github_alias, lab_id, task_id)

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
        f"Attempts used: {attempts + 1}/{MAX_ATTEMPTS_PER_TASK}",
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


