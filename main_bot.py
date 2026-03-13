"""Main entry point for the Telegram bot."""

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand

from bot.config import BOT_TOKEN
from bot.database import init_db
from bot.middlewares import AuthMiddleware
from bot.handlers import register, start, labs, check

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger(__name__)


async def main() -> None:
    """Initialize and run the bot."""
    # Initialize database
    logger.info("Initializing database...")
    await init_db()

    # Initialize bot and dispatcher
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()

    # Register middleware (outer so db_user is available during filter evaluation)
    dp.message.outer_middleware(AuthMiddleware())
    dp.callback_query.outer_middleware(AuthMiddleware())

    # Register routers — order matters:
    # check.router first so FSM states (e.g., waiting_for_server_ip) are
    # handled before the catch-all in start.router.
    # register.router handles unregistered users (FSM states),
    # start.router catches /start and unrecognized messages last.
    dp.include_router(check.router)
    dp.include_router(register.router)
    dp.include_router(labs.router)
    dp.include_router(start.router)

    # Set bot command menu
    await bot.set_my_commands([
        BotCommand(command="start", description="Check your labs"),
        BotCommand(command="reset", description="View and reset stored settings"),
    ])

    # Start polling
    logger.info("Starting bot...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
        sys.exit(1)
