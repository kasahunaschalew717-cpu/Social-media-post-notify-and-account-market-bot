from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from sqlalchemy import select

from core.config import settings
from core.logger import logger
from core.database import async_session_factory
from models.user import User, UserRole
from bot.keyboards import main_menu_keyboard


async def get_or_create_user(telegram_id: int, username: str | None, first_name: str | None) -> User:
    """Helper to ensure the user exists in our PostgreSQL database."""
    async with async_session_factory() as session:
        stmt = select(User).where(User.telegram_id == telegram_id)
        res = await session.execute(stmt)
        user = res.scalar_one_or_none()

        if not user:
            role = UserRole.ADMIN if telegram_id in settings.ADMIN_USER_IDS else UserRole.USER
            user = User(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                role=role,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            logger.info(f"Registered new user #{telegram_id} (@{username}) with role {role.value}")
        else:
            # Update username if changed
            if username and user.username != username:
                user.username = username
                await session.commit()

        return user


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command."""
    tg_user = update.effective_user
    if not tg_user:
        return

    user = await get_or_create_user(
        telegram_id=tg_user.id,
        username=tg_user.username,
        first_name=tg_user.first_name,
    )

    is_admin = user.role == UserRole.ADMIN or tg_user.id in settings.ADMIN_USER_IDS

    welcome_text = (
        f"👋 <b>Welcome, {tg_user.first_name}!</b>\n\n"
        "I am your <b>Dual-Engine Social Media Suite</b>:\n\n"
        "🔔 <b>1. Creator Alert Engine:</b>\n"
        "Subscribe to influencers and creators across YouTube, TikTok, Instagram, "
        "Facebook, and Telegram public channels. Receive instant alerts the moment new content drops.\n\n"
        "🛒 <b>2. Verified Account Marketplace:</b>\n"
        "Buy and sell social media accounts with complete peace of mind. Every listing is backed by "
        "<b>mandatory ownership verification</b> and protected by our <b>secure escrow state machine</b>.\n\n"
        "Use the buttons below to begin:"
    )

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            welcome_text,
            reply_markup=main_menu_keyboard(is_admin=is_admin),
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.message.reply_text(
            welcome_text,
            reply_markup=main_menu_keyboard(is_admin=is_admin),
            parse_mode=ParseMode.HTML,
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /help command and FAQ display."""
    help_text = (
        "📖 <b>System Guide & Security Policy</b>\n\n"
        "🔔 <b>Notification Engine:</b>\n"
        "• YouTube: Uses Google PubSubHubbub (WebSub) push notifications with HMAC-SHA1 signature verification.\n"
        "• Telegram: Polls official public channel web preview (/s/{channel}).\n"
        "• TikTok & Meta: Uses compliant partner APIs and authorized Business Discovery. No unauthenticated bot scraping.\n\n"
        "🛡️ <b>Ownership Verification Gate:</b>\n"
        "• Sellers must prove account control before listings go live.\n"
        "• A unique challenge code (e.g., <code>VERIFY-7X9K2A</code>) must be placed in the account bio, description, or community post.\n"
        "• Telegram channels can add the bot as admin temporarily.\n"
        "• High-value accounts (>$500) undergo secondary review.\n\n"
        "🤝 <b>Escrow State Machine:</b>\n"
        "1. <b>Awaiting Payment:</b> Buyer deposits funds into platform escrow.\n"
        "2. <b>Funds Held:</b> Seller provides credentials through an encrypted one-time vault.\n"
        "3. <b>Inspection Window:</b> Buyer has 48–72h to secure the account (change email, phone, and 2FA).\n"
        "4. <b>Release:</b> Funds are released to the seller only after the buyer confirms full control.\n"
        "5. <b>Dispute SLA:</b> Admin responds to disputes within 24 hours.\n\n"
        "⚠️ <b>Platform Terms Compliance:</b> Please check account platform terms regarding account transfers. "
        "Our escrow protects funds and verified ownership handover."
    )

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            help_text,
            reply_markup=main_menu_keyboard(is_admin=update.effective_user.id in settings.ADMIN_USER_IDS),
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.message.reply_text(
            help_text,
            reply_markup=main_menu_keyboard(is_admin=update.effective_user.id in settings.ADMIN_USER_IDS),
            parse_mode=ParseMode.HTML,
        )

