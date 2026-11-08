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
from sqlalchemy import select

from core.config import settings
from core.logger import logger
from core.database import async_session_factory
from models.monitored_source import PlatformType
from models.listing import MarketplaceListing, ListingStatus
from models.verification import OwnershipVerification, VerificationStatus
from bot.states import SellState
from bot.keyboards import platform_selection_keyboard, verification_action_keyboard
from marketplace.verification import verification_service
from bot.handlers.start import get_or_create_user


async def sell_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Starts the /sell wizard."""
    text = (
        "💼 <b>List Account for Sale</b>\n\n"
        "Welcome to our verified marketplace! Before any listing becomes visible to buyers, "
        "you must complete our <b>ownership verification challenge</b> to prove you control the account.\n\n"
        "Which platform is this account on?"
    )
    kb = platform_selection_keyboard(prefix="sell_plat")

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

    return SellState.SELECT_PLATFORM


async def sell_platform_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    platform_str = query.data.split(":")[1]
    context.user_data["sell_platform"] = platform_str

    await query.edit_message_text(
        f"Platform: <b>{platform_str}</b>\n\n"
        "Please enter the <b>account username or channel handle</b> (e.g., <code>@mychannel</code>):",
        parse_mode=ParseMode.HTML,
    )
    return SellState.ENTER_HANDLE


async def sell_handle_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    handle = update.message.text.strip()
    context.user_data["sell_handle"] = handle

    await update.message.reply_text(
        f"Account Handle: <b>{handle}</b>\n\n"
        "What is your <b>asking price in USD ($)</b>?\n"
        "<i>(e.g., 150 or 750)</i>",
        parse_mode=ParseMode.HTML,
    )
    return SellState.ENTER_PRICE


async def sell_price_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace("$", "").replace(",", "")
    try:
        price = float(text)
        if price < 5.0:
            await update.message.reply_text("Minimum asking price is $5.00. Please enter a valid amount:")
            return SellState.ENTER_PRICE
    except ValueError:
        await update.message.reply_text("Please enter a valid numeric price (e.g., 250):")
        return SellState.ENTER_PRICE

    context.user_data["sell_price"] = price
    await update.message.reply_text(
        f"Asking Price: <b>${price:.2f}</b>\n\n"
        "What is the current <b>follower/subscriber count</b>?\n"
        "<i>(e.g., 25000)</i>",
        parse_mode=ParseMode.HTML,
    )
    return SellState.ENTER_FOLLOWERS


async def sell_followers_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(",", "")
    try:
        followers = int(text)
    except ValueError:
        await update.message.reply_text("Please enter a whole number for followers (e.g., 10000):")
        return SellState.ENTER_FOLLOWERS

    context.user_data["sell_followers"] = followers
    niches = ["Tech", "Gaming", "Crypto", "Lifestyle", "Fashion", "Memes", "Business", "General"]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(n, callback_data=f"niche:{n}") for n in niches[:4]],
        [InlineKeyboardButton(n, callback_data=f"niche:{n}") for n in niches[4:]],
    ])

    await update.message.reply_text(
        f"Follower Count: <b>{followers:,}</b>\n\nSelect the <b>niche/category</b> for this account:",
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
    )
    return SellState.ENTER_NICHE


async def sell_niche_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    niche = query.data.split(":")[1]
    context.user_data["sell_niche"] = niche

    await query.edit_message_text(
        f"Niche: <b>{niche}</b>\n\n"
        "Please provide a <b>description</b> for the listing:\n"
        "<i>Include details like audience demographics, monthly revenue/views, reason for selling, and original email status.</i>",
        parse_mode=ParseMode.HTML,
    )
    return SellState.ENTER_DESCRIPTION


async def sell_description_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    desc = update.message.text.strip()
    data = context.user_data

    tg_user = update.effective_user
    db_user = await get_or_create_user(tg_user.id, tg_user.username, tg_user.first_name)

    # Create listing in database
    async with async_session_factory() as session:
        listing = MarketplaceListing(
            seller_id=db_user.id,
            platform=PlatformType(data["sell_platform"]),
            account_handle=data["sell_handle"],
            asking_price_usd=data["sell_price"],
            follower_count=data["sell_followers"],
            niche=data["sell_niche"],
            description=desc,
            status=ListingStatus.PENDING_VERIFICATION,
        )
        session.add(listing)
        await session.commit()
        await session.refresh(listing)

    # Initiate Verification Challenge
    verif, instructions = await verification_service.initiate_verification(listing.id)

    # If high value, append warning
    if data["sell_price"] >= settings.HIGH_VALUE_THRESHOLD_USD:
        instructions += (
            f"\n\n⚠️ <b>High-Value Protection:</b> Because asking price is ≥ ${settings.HIGH_VALUE_THRESHOLD_USD:.0f}, "
            f"a secondary dashboard check or 7-day cooling-off period applies."
        )

    await update.message.reply_text(
        instructions,
        reply_markup=verification_action_keyboard(verif.id),
        parse_mode=ParseMode.HTML,
    )
    return ConversationHandler.END


async def check_verification_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the 'Verify Now' button click."""
    query = update.callback_query
    await query.answer()

    verif_id = int(query.data.split(":")[1])
    await query.edit_message_text("🔄 Checking profile for verification challenge... Please wait.")

    is_verified, msg = await verification_service.check_challenge(verif_id)

    if is_verified:
        await query.edit_message_text(
            f"{msg}\n\n"
            "Your listing is now <b>LIVE</b> in /market! Buyers can now place escrow orders.",
            parse_mode=ParseMode.HTML,
        )
    else:
        await query.edit_message_text(
            f"{msg}\n\n"
            "Please ensure the code is saved on your profile and tap below to retry:",
            reply_markup=verification_action_keyboard(verif_id),
            parse_mode=ParseMode.HTML,
        )


async def my_listings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows seller's listings and their verification state."""
    tg_user = update.effective_user
    db_user = await get_or_create_user(tg_user.id, tg_user.username, tg_user.first_name)

    async with async_session_factory() as session:
        stmt = (
            select(MarketplaceListing)
            .where(MarketplaceListing.seller_id == db_user.id)
            .order_by(MarketplaceListing.created_at.desc())
        )
        res = await session.execute(stmt)
        listings = res.scalars().all()

    if not listings:
        msg = "You have not listed any accounts for sale.\nTap /sell to list an account!"
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(msg)
        else:
            await update.message.reply_text(msg)
        return

    text = "📋 <b>Your Marketplace Listings:</b>\n\n"
    for l in listings:
        badge = "✅ Verified" if l.is_verified else "⏳ Unverified"
        text += (
            f"• <b>{l.platform.value}</b>: <code>{l.account_handle}</code>\n"
            f"  Price: ${l.asking_price_usd:.2f} | Followers: {l.follower_count:,}\n"
            f"  Status: <code>{l.status.value}</code> ({badge})\n\n"
        )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ List Another Account", callback_data="nav_sell")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="nav_main")],
    ])

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


def get_sell_conversation_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CommandHandler("sell", sell_start),
            CallbackQueryHandler(sell_start, pattern="^nav_sell$"),
        ],
        states={
            SellState.SELECT_PLATFORM: [
                CallbackQueryHandler(sell_platform_selected, pattern="^sell_plat:"),
            ],
            SellState.ENTER_HANDLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, sell_handle_entered),
            ],
            SellState.ENTER_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, sell_price_entered),
            ],
            SellState.ENTER_FOLLOWERS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, sell_followers_entered),
            ],
            SellState.ENTER_NICHE: [
                CallbackQueryHandler(sell_niche_selected, pattern="^niche:"),
            ],
            SellState.ENTER_DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, sell_description_entered),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(sell_start, pattern="^cancel_action$"),
            CommandHandler("cancel", sell_start),
        ],
        per_user=True,
    )

