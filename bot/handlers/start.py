"""Handler for /start command (registered users)."""

from typing import Any

from aiogram import Router
from aiogram.filters import CommandStart, BaseFilter
from aiogram.types import Message, TelegramObject
from aiogram.fsm.context import FSMContext

from ..database import User
from ..keyboards import get_labs_keyboard

router = Router()


class IsRegistered(BaseFilter):
    """Filter that passes only when db_user is set (registered)."""

    async def __call__(self, event: TelegramObject, db_user: Any = None) -> bool:
        return db_user is not None


@router.message(CommandStart(), IsRegistered())
async def cmd_start(message: Message, db_user: User, state: FSMContext) -> None:
    """Handle /start command for registered users — clear any FSM state and show task list."""
    await state.clear()
    await message.answer(
        f"Welcome, {db_user.github_alias}!\n\n"
        "Choose a lab:",
        reply_markup=get_labs_keyboard(),
    )
