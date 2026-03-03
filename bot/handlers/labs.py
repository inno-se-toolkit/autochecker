"""Handler for lab selection and VM IP change callbacks."""

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from ..database import User, get_server_ip, get_server_ip_owner, set_server_ip
from ..ip_utils import validate_ip
from ..keyboards import get_labs_keyboard, get_tasks_keyboard

router = Router()


class ChangeIPStates(StatesGroup):
    waiting_for_new_ip = State()


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
async def callback_back_to_labs(callback: CallbackQuery, db_user: User) -> None:
    """Return to the lab selection menu."""
    await callback.answer()
    server_ip = await get_server_ip(db_user.tg_id)
    await callback.message.edit_text(
        "Choose a lab:",
        reply_markup=get_labs_keyboard(server_ip=server_ip),
    )


@router.callback_query(F.data == "change_ip")
async def callback_change_ip(callback: CallbackQuery, db_user: User, state: FSMContext) -> None:
    """Show student profile and prompt for new VM IP."""
    current_ip = await get_server_ip(db_user.tg_id)

    # Build profile info
    profile_lines = [
        "<b>Your profile:</b>",
        f"  GitHub: <code>{db_user.github_alias}</code>",
        f"  Email: <code>{db_user.email}</code>",
        f"  VM IP: <code>{current_ip}</code>" if current_ip else "  VM IP: not set",
    ]
    profile = "\n".join(profile_lines)

    if current_ip:
        prompt = (
            f"{profile}\n\n"
            "Send the new IP address (e.g., <code>10.93.25.100</code>),\n"
            "or /start to cancel:"
        )
    else:
        prompt = (
            f"{profile}\n\n"
            "Send your VM IP address (e.g., <code>10.93.25.100</code>),\n"
            "or /start to cancel:"
        )
    await callback.answer()
    await callback.message.edit_text(prompt)
    await state.set_state(ChangeIPStates.waiting_for_new_ip)


@router.message(ChangeIPStates.waiting_for_new_ip)
async def process_change_ip(message: Message, db_user: User, state: FSMContext) -> None:
    """Validate and save the new VM IP, then return to labs menu."""
    ip = message.text.strip() if message.text else ""

    valid, error_msg = validate_ip(ip)
    if not valid:
        await message.answer(error_msg)
        return

    existing_owner = await get_server_ip_owner(ip, db_user.tg_id)
    if existing_owner:
        await message.answer(
            "This IP is already registered to another student.\n"
            "Each student must use their own VM. Please enter your unique VM IP:"
        )
        return

    await set_server_ip(db_user.tg_id, ip)
    await state.clear()

    await message.answer(
        f"VM IP updated to <code>{ip}</code>\n\nChoose a lab:",
        reply_markup=get_labs_keyboard(server_ip=ip),
    )
