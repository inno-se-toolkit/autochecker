"""Inline keyboards for the bot."""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .config import get_active_tasks, get_lab_titles, MAX_ATTEMPTS_PER_TASK
from .database import get_task_stats, has_passed_task


def get_labs_keyboard(server_ip: str = "") -> InlineKeyboardMarkup:
    """Create inline keyboard with available labs + VM IP button."""
    builder = InlineKeyboardBuilder()
    for lab_id, title in get_lab_titles().items():
        builder.add(
            InlineKeyboardButton(text=title, callback_data=f"lab:{lab_id}")
        )
    builder.adjust(1)
    ip_label = f"VM: {server_ip}" if server_ip else "Set VM IP"
    builder.row(InlineKeyboardButton(text=ip_label, callback_data="change_ip"))
    return builder.as_markup()


async def get_tasks_keyboard(tg_id: int, lab_id: str) -> InlineKeyboardMarkup:
    """Create inline keyboard with available tasks for a specific lab."""
    builder = InlineKeyboardBuilder()
    tasks = [t for t in get_active_tasks() if t.lab_id == lab_id]
    stats = await get_task_stats(tg_id)

    # Cache prerequisite unlock status to avoid repeated DB queries
    unlocked_cache: dict[str, bool] = {}

    for task in tasks:
        key = f"{task.lab_id}:{task.task_id}"
        task_stat = stats.get(key, {})
        attempts = task_stat.get("attempts", 0)
        score = task_stat.get("score")

        # Check prerequisite: unlock if passed OR all attempts spent
        locked = False
        if task.prerequisite:
            prereq_key = f"{task.lab_id}:{task.prerequisite}"
            if prereq_key not in unlocked_cache:
                passed = await has_passed_task(tg_id, task.lab_id, task.prerequisite)
                prereq_stat = stats.get(prereq_key, {})
                prereq_attempts = prereq_stat.get("attempts", 0)
                unlocked_cache[prereq_key] = passed or prereq_attempts >= MAX_ATTEMPTS_PER_TASK
            if not unlocked_cache[prereq_key]:
                locked = True

        if locked:
            label = f"🔒 {task.title}"
            callback_data = f"locked:{task.prerequisite}"
        else:
            # Status icon
            failed = task_stat.get("failed")
            if score is not None and failed == 0:
                icon = "✅"
            elif score is not None:
                icon = "⚠️"
            else:
                icon = "📝"

            remaining = MAX_ATTEMPTS_PER_TASK - attempts
            score_part = f" {score}" if score else ""
            passed = score is not None and failed == 0
            if passed:
                attempts_part = ""
            elif remaining == 1:
                attempts_part = " (1 attempt left)"
            elif remaining > 1:
                attempts_part = f" ({remaining} attempts left)"
            else:
                attempts_part = " (no attempts left)"
            label = f"{icon} {task.title}{score_part}{attempts_part}"
            callback_data = f"check:{task.lab_id}:{task.task_id}"

        builder.add(
            InlineKeyboardButton(text=label, callback_data=callback_data)
        )

    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="← Back to labs", callback_data="back_to_labs"))
    return builder.as_markup()


