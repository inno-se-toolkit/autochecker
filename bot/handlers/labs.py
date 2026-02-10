"""Handler for lab selection callbacks."""

from aiogram import Router, F
from aiogram.types import CallbackQuery

from ..database import User
from ..keyboards import get_labs_keyboard, get_tasks_keyboard

router = Router()


@router.callback_query(F.data.startswith("lab:"))
async def callback_select_lab(callback: CallbackQuery, db_user: User) -> None:
    """Show tasks for the selected lab."""
    lab_id = callback.data.split(":", 1)[1]
    await callback.answer()
    await callback.message.edit_text(
        "Choose a task to check:",
        reply_markup=await get_tasks_keyboard(db_user.tg_id, lab_id),
    )


@router.callback_query(F.data == "back_to_labs")
async def callback_back_to_labs(callback: CallbackQuery) -> None:
    """Return to the lab selection menu."""
    await callback.answer()
    await callback.message.edit_text(
        "Choose a lab:",
        reply_markup=get_labs_keyboard(),
    )
