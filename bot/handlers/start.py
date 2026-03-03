"""Handler for /start command (registered users)."""

from typing import Any

from aiogram import Router
from aiogram.filters import CommandStart, BaseFilter
from aiogram.types import Message, TelegramObject
from aiogram.fsm.context import FSMContext

from ..database import User, get_server_ip
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
    server_ip = await get_server_ip(db_user.tg_id)
    await message.answer(
        f"Welcome, {db_user.github_alias}!\n\n"
        "Choose a lab:",
        reply_markup=get_labs_keyboard(server_ip=server_ip),
    )


@router.message(IsRegistered())
async def catch_all_registered(message: Message, db_user: User, state: FSMContext) -> None:
    """Catch any unrecognized message from a registered user — show labs menu."""
    await state.clear()
    server_ip = await get_server_ip(db_user.tg_id)
    await message.answer(
        "Choose a lab:",
        reply_markup=get_labs_keyboard(server_ip=server_ip),
    )
