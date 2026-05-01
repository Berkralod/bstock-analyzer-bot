from telegram.ext import Application, CommandHandler, MessageHandler, filters
import config
from bot.commands import (
    cmd_start,
    cmd_help,
    cmd_analyze,
    cmd_history,
    cmd_status,
    cmd_credentials,
    handle_message,
)


def build_application() -> Application:
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("analyze", cmd_analyze))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("credentials", cmd_credentials))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    return app
