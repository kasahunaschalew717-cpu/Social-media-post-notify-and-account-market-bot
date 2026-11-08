from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
from sqlalchemy import select, and_

from core.logger import logger
from core.database import async_session_factory
from models.monitored_source import MonitoredSource, PlatformType
from models.subscription import Subscription
from models.user import User
from bot.states import SubscribeState
from bot.keyboards import platform_selection_keyboard
from services.youtube import youtube_monitor
from services.telegram import telegram_monitor
from services.tiktok import tiktok_monitor
from services.instagram import instagram_monitor
from services.facebook import facebook_monitor
from bot.handlers.start import get_or_create_user


async def subscribe_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Starts the /subscribe flow by asking for the platform."""
    text = "🔔 <b>Add Creator Subscription</b>\n\nWhich platform is the creator on?"
    keyboard = platform_selection_keyboard(prefix="sub_plat")

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)

    return SubscribeState.SELECT_PLATFORM


async def subscribe_platform_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Captures the chosen platform and asks for handle or URL."""
    query = update.callback_query
    await query.answer()

    data = query.data.split(":")
    if len(data) < 2:
        return ConversationHandler.END

    platform_str = data[1]
    context.user_data["sub_platform"] = platform_str

    prompt = (
        f"Selected platform: <b>{platform_str}</b>\n\n"
        "Please send the <b>creator handle, channel username, or profile URL</b>.\n\n"
        "<i>Examples:</i>\n"
        "• YouTube: <code>@mkbhd</code> or <code>https://youtube.com/c/mkbhd</code>\n"
        "• Telegram: <code>@durov</code> or <code>https://t.me/durov</code>\n"
        "• TikTok: <code>@khaby.lame</code>\n"
        "• Instagram: <code>@cristiano</code>\n"
        "• Facebook: <code>@nasa</code>"
    )
    cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]])
    await query.edit_message_text(prompt, reply_markup=cancel_kb, parse_mode=ParseMode.HTML)
    return SubscribeState.ENTER_HANDLE


async def subscribe_handle_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Validates the creator handle with the platform monitor and stores subscription."""
    raw_input = update.message.text.strip()
    platform_str = context.user_data.get("sub_platform")

    if not platform_str:
        await update.message.reply_text("Session timed out. Please send /subscribe again.")
        return ConversationHandler.END

    platform_type = PlatformType(platform_str)
    status_msg = await update.message.reply_text(
        f"🔍 Validating <b>{raw_input}</b> on {platform_str}...",
        parse_mode=ParseMode.HTML,
    )

    # Dispatch to monitor validation
    val_result = None
    if platform_type == PlatformType.YOUTUBE:
        val_result = await youtube_monitor.validate_source(raw_input)
    elif platform_type == PlatformType.TELEGRAM:
        val_result = await telegram_monitor.validate_source(raw_input)
    elif platform_type == PlatformType.TIKTOK:
        val_result = await tiktok_monitor.validate_source(raw_input)
    elif platform_type == PlatformType.INSTAGRAM:
        val_result = await instagram_monitor.validate_source(raw_input)
    elif platform_type == PlatformType.FACEBOOK:
        val_result = await facebook_monitor.validate_source(raw_input)

    if not val_result or not val_result.is_valid:
        err = val_result.error_message if val_result else "Source not found."
        await status_msg.edit_text(
            f"❌ <b>Validation Failed:</b> {err}\n\nPlease try again with a valid handle or profile link.",
            parse_mode=ParseMode.HTML,
        )
        return SubscribeState.ENTER_HANDLE

    # Ensure user exists
    tg_user = update.effective_user
    db_user = await get_or_create_user(tg_user.id, tg_user.username, tg_user.first_name)

    # Save to database
    async with async_session_factory() as session:
        # Check if MonitoredSource exists
        stmt = select(MonitoredSource).where(
            MonitoredSource.platform == platform_type,
            MonitoredSource.source_id == val_result.source_id,
        )
        res = await session.execute(stmt)
        source = res.scalar_one_or_none()

        if not source:
            source = MonitoredSource(
                platform=platform_type,
                handle=val_result.normalized_handle,
                source_id=val_result.source_id,
                display_name=val_result.display_name,
                url=val_result.profile_url,
                metadata_json=val_result.metadata,
                is_active=True,
            )
            session.add(source)
            await session.commit()
            await session.refresh(source)

            # If YouTube, subscribe to PubSubHubbub push notifications
            if platform_type == PlatformType.YOUTUBE:
                await youtube_monitor.register_hub_subscription(source.source_id)

        # Check if already subscribed
        sub_stmt = select(Subscription).where(
            Subscription.user_id == db_user.id,
            Subscription.source_id == source.id,
        )
        sub_res = await session.execute(sub_stmt)
        sub = sub_res.scalar_one_or_none()

        if sub:
            if not sub.is_active:
                sub.is_active = True
                await session.commit()
                await status_msg.edit_text(
                    f"✅ Re-activated subscription to <b>{source.handle}</b> on {platform_str}!",
                    parse_mode=ParseMode.HTML,
                )
            else:
                await status_msg.edit_text(
                    f"ℹ️ You are already subscribed to <b>{source.handle}</b> on {platform_str}.",
                    parse_mode=ParseMode.HTML,
                )
        else:
            new_sub = Subscription(user_id=db_user.id, source_id=source.id)
            session.add(new_sub)
            await session.commit()
            await status_msg.edit_text(
                f"🎉 <b>Subscribed successfully!</b>\n\n"
                f"Creator: <b>{source.display_name or source.handle}</b> ({source.handle})\n"
                f"Platform: <b>{platform_str}</b>\n\n"
                "You will receive immediate Telegram alerts whenever new content is published.",
                parse_mode=ParseMode.HTML,
            )

    return ConversationHandler.END


async def my_subscriptions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays list of current active subscriptions with unsubscribe buttons."""
    tg_user = update.effective_user
    db_user = await get_or_create_user(tg_user.id, tg_user.username, tg_user.first_name)

    async with async_session_factory() as session:
        stmt = (
            select(Subscription, MonitoredSource)
            .join(MonitoredSource, MonitoredSource.id == Subscription.source_id)
            .where(
                Subscription.user_id == db_user.id,
                Subscription.is_active == True,
            )
        )
        res = await session.execute(stmt)
        rows = res.all()

    if not rows:
        msg = "You have no active subscriptions.\nTap /subscribe to add creators!"
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(msg)
        else:
            await update.message.reply_text(msg)
        return

    text = "📋 <b>Your Active Subscriptions:</b>\n\n"
    buttons = []
    for sub, src in rows:
        text += f"• <b>{src.platform.value}</b>: <a href=\"{src.url}\">{src.handle}</a>\n"
        buttons.append([
            InlineKeyboardButton(f"❌ Remove {src.handle}", callback_data=f"unsub:{sub.id}")
        ])

    buttons.append([InlineKeyboardButton("➕ Add New Subscription", callback_data="nav_notifications")])
    buttons.append([InlineKeyboardButton("🏠 Main Menu", callback_data="nav_main")])

    kb = InlineKeyboardMarkup(buttons)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


async def unsubscribe_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deactivates a subscription."""
    query = update.callback_query
    await query.answer()

    sub_id = int(query.data.split(":")[1])
    async with async_session_factory() as session:
        stmt = select(Subscription).where(Subscription.id == sub_id)
        res = await session.execute(stmt)
        sub = res.scalar_one_or_none()
        if sub:
            sub.is_active = False
            await session.commit()
            await query.edit_message_text("✅ Subscription removed.")
        else:
            await query.edit_message_text("Subscription not found.")


async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancels any active conversation."""
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("❌ Action cancelled.")
    else:
        await update.message.reply_text("❌ Action cancelled.")
    return ConversationHandler.END


def get_subscribe_conversation_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CommandHandler("subscribe", subscribe_start),
            CallbackQueryHandler(subscribe_start, pattern="^nav_notifications$"),
        ],
        states={
            SubscribeState.SELECT_PLATFORM: [
                CallbackQueryHandler(subscribe_platform_selected, pattern="^sub_plat:"),
            ],
            SubscribeState.ENTER_HANDLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, subscribe_handle_entered),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(cancel_conversation, pattern="^cancel_action$"),
            CommandHandler("cancel", cancel_conversation),
        ],
        per_user=True,
    )

