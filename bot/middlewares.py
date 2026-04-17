"""Middleware for checking user authorization."""

from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject

from .config import ALLOWED_EMAILS
from .database import get_user, delete_user


class AuthMiddleware(BaseMiddleware):
    """Middleware that loads user from DB (or sets None for unregistered)."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        user_id = None
        if isinstance(event, (Message, CallbackQuery)):
            user_id = event.from_user.id if event.from_user else None

        if user_id is None:
            return None

        user = await get_user(user_id)

        # If whitelist is active, evict users whose email is not on the roster
        if user and ALLOWED_EMAILS and user.email.lower() not in ALLOWED_EMAILS:
            if not user.is_admin:
                await delete_user(user_id)
                user = None

        data["db_user"] = user  # None for unregistered, User for registered

        return await handler(event, data)
