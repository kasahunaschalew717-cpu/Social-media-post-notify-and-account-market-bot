from telegram import Update
from telegram.ext import ContextTypes
from core.logger import logger


async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Logs the error and sends a friendly notice to the user if applicable."""
    logger.error("Exception while handling an update:", exc_info=context.error)

    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ An unexpected system error occurred. Our engineering team has been notified."
            )
        except Exception:
            pass

