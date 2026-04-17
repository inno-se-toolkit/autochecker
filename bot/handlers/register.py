"""Handler for student self-registration."""

import re
from typing import Any, Dict

from aiogram import Router, F
from aiogram.filters import CommandStart, BaseFilter
from aiogram.types import Message, CallbackQuery, TelegramObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from ..config import ALLOWED_EMAILS
from ..database import User, upsert_user, get_user_by_email, get_user_by_github
from ..keyboards import get_labs_keyboard

router = Router()

EMAIL_REGEX = re.compile(r"^[^@\s]+@innopolis\.university$", re.IGNORECASE)
GITHUB_REGEX = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?$")


class NotRegistered(BaseFilter):
    """Filter that passes only when db_user is None (unregistered)."""

    async def __call__(self, event: TelegramObject, db_user: Any = None) -> bool:
        return db_user is None


class RegistrationStates(StatesGroup):
    waiting_for_email = State()
    waiting_for_github = State()


not_registered = NotRegistered()


@router.message(CommandStart(), not_registered)
async def cmd_start_unregistered(message: Message, state: FSMContext) -> None:
    """Handle /start for unregistered users — begin registration."""
    await state.clear()
    await state.set_state(RegistrationStates.waiting_for_email)
    await message.answer(
        "Welcome! To get started, please register.\n\n"
        "Send your Innopolis University email (e.g. <code>a.student@innopolis.university</code>):"
    )


@router.message(RegistrationStates.waiting_for_email)
async def process_email(message: Message, state: FSMContext) -> None:
    """Validate email and move to GitHub alias step."""
    email = message.text.strip().lower() if message.text else ""

    if not EMAIL_REGEX.match(email):
        await message.answer(
            "Invalid email. It must end with <code>@innopolis.university</code>.\n\nTry again:"
        )
        return

    if ALLOWED_EMAILS and email not in ALLOWED_EMAILS:
        await message.answer(
            "This email is not in the course roster.\n"
            "Please use the email registered in Moodle.\n\nTry again:"
        )
        return

    existing = await get_user_by_email(email)
    if existing and existing.tg_id != message.from_user.id:
        await state.clear()
        await message.answer(
            "This email is already registered to another account.\n"
            "Each email can only be used once (first-come-first-served).\n\n"
            "Send /start to try again with a different email."
        )
        return

    await state.update_data(email=email)
    await state.set_state(RegistrationStates.waiting_for_github)
    await message.answer(
        f"Email: <code>{email}</code>\n\n"
        "Now send your GitHub username (e.g. <code>johndoe</code>):"
    )


@router.message(RegistrationStates.waiting_for_github)
async def process_github(message: Message, state: FSMContext) -> None:
    """Validate GitHub alias, create/update user, show tasks."""
    alias = message.text.strip().lstrip("@") if message.text else ""

    if not alias or not GITHUB_REGEX.match(alias):
        await message.answer(
            "Invalid GitHub username. Use only letters, digits, and hyphens.\n\nTry again:"
        )
        return

    existing = await get_user_by_github(alias)
    if existing and existing.tg_id != message.from_user.id:
        await state.clear()
        await message.answer(
            f"GitHub username <code>{alias}</code> is already registered to another account.\n"
            "Each GitHub account can only be linked once (first-come-first-served).\n\n"
            "Send /start to try again with a different username."
        )
        return

    data = await state.get_data()
    email = data["email"]
    tg_username = message.from_user.username or ""

    try:
        await upsert_user(
            tg_id=message.from_user.id,
            email=email,
            github_alias=alias,
            tg_username=tg_username,
            student_group=ALLOWED_EMAILS.get(email, ""),
        )
    except ValueError as e:
        await state.clear()
        await message.answer(
            f"{e}\n\nSend /start to try again."
        )
        return

    await state.clear()

    await message.answer(
        f"Registration complete!\n\n"
        f"Email: <code>{email}</code>\n"
        f"GitHub: <code>{alias}</code>\n\n"
        "Choose a lab:",
        reply_markup=get_labs_keyboard(),
    )


@router.message(not_registered)
async def catch_unregistered(message: Message, state: FSMContext) -> None:
    """Catch any message from an unregistered user who is not in FSM flow."""
    await state.clear()
    await state.set_state(RegistrationStates.waiting_for_email)
    await message.answer(
        "You are not registered yet. Let's fix that!\n\n"
        "Send your Innopolis University email (e.g. <code>a.student@innopolis.university</code>):"
    )


