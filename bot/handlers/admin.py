from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler
from sqlalchemy import select, func

from core.config import settings
from core.logger import logger
from core.database import async_session_factory
from models.user import User, UserRole
from models.listing import MarketplaceListing, ListingStatus
from models.escrow import EscrowTransaction, EscrowStatus
from models.verification import OwnershipVerification, VerificationStatus
from models.monitored_source import MonitoredSource
from models.subscription import Subscription
from bot.keyboards import admin_dashboard_keyboard, admin_dispute_keyboard
from marketplace.escrow import escrow_state_machine
from workers.tasks import poll_all_social_sources


async def is_user_admin(telegram_id: int) -> bool:
    if telegram_id in settings.ADMIN_USER_IDS:
        return True
    async with async_session_factory() as session:
        stmt = select(User).where(User.telegram_id == telegram_id)
        res = await session.execute(stmt)
        user = res.scalar_one_or_none()
        return bool(user and user.role == UserRole.ADMIN)


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin dashboard command."""
    tg_user = update.effective_user
    if not await is_user_admin(tg_user.id):
        await update.message.reply_text("⛔ Unauthorized access.")
        return

    text = (
        "🛡️ <b>Platform Admin Dashboard</b>\n\n"
        "Select an administrative module to manage:"
    )
    kb = admin_dashboard_keyboard()

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


async def admin_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays platform metrics."""
    query = update.callback_query
    await query.answer()

    async with async_session_factory() as session:
        total_users = (await session.execute(select(func.count(User.id)))).scalar() or 0
        total_sources = (await session.execute(select(func.count(MonitoredSource.id)))).scalar() or 0
        total_subs = (await session.execute(select(func.count(Subscription.id)))).scalar() or 0
        active_listings = (
            await session.execute(
                select(func.count(MarketplaceListing.id)).where(MarketplaceListing.status == ListingStatus.ACTIVE)
            )
        ).scalar() or 0
        escrow_completed = (
            await session.execute(
                select(func.count(EscrowTransaction.id)).where(EscrowTransaction.status == EscrowStatus.COMPLETED)
            )
        ).scalar() or 0
        escrow_vol = (
            await session.execute(
                select(func.sum(EscrowTransaction.amount_usd)).where(EscrowTransaction.status == EscrowStatus.COMPLETED)
            )
        ).scalar() or 0.0

    stats_text = (
        "📊 <b>Platform Statistics:</b>\n\n"
        f"• Total Users: <b>{total_users:,}</b>\n"
        f"• Monitored Creators/Sources: <b>{total_sources:,}</b>\n"
        f"• Active Subscriptions: <b>{total_subs:,}</b>\n"
        f"• Live Marketplace Listings: <b>{active_listings:,}</b>\n"
        f"• Completed Escrows: <b>{escrow_completed:,}</b>\n"
        f"• Total Volume: <b>${float(escrow_vol):,.2f} USD</b>\n"
    )

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="nav_admin")]])
    await query.edit_message_text(stats_text, reply_markup=kb, parse_mode=ParseMode.HTML)


async def admin_verifications_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lists pending verifications."""
    query = update.callback_query
    await query.answer()

    async with async_session_factory() as session:
        stmt = (
            select(OwnershipVerification, MarketplaceListing)
            .join(MarketplaceListing, MarketplaceListing.id == OwnershipVerification.listing_id)
            .where(OwnershipVerification.status == VerificationStatus.PENDING)
            .order_by(OwnershipVerification.created_at.desc())
            .limit(10)
        )
        res = await session.execute(stmt)
        items = res.all()

    if not items:
        await query.edit_message_text(
            "✅ No pending verifications.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="nav_admin")]]),
        )
        return

    text = f"📋 <b>Pending Ownership Verifications ({len(items)}):</b>\n\n"
    buttons = []
    for verif, listing in items:
        text += (
            f"• #{listing.id} <b>{listing.platform.value}</b>: <code>{listing.account_handle}</code>\n"
            f"  Code: <code>{verif.challenge_code}</code> | Attempts: {verif.verification_attempts}\n"
            f"  Price: ${listing.asking_price_usd:.2f}\n\n"
        )
        buttons.append([
            InlineKeyboardButton(f"✅ Manual Approve #{listing.id}", callback_data=f"adm_appr_verif:{listing.id}"),
            InlineKeyboardButton(f"❌ Reject #{listing.id}", callback_data=f"adm_rej_verif:{listing.id}"),
        ])

    buttons.append([InlineKeyboardButton("« Back", callback_data="nav_admin")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)


async def admin_approve_verification_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    listing_id = int(query.data.split(":")[1])
    async with async_session_factory() as session:
        stmt = select(MarketplaceListing).where(MarketplaceListing.id == listing_id)
        res = await session.execute(stmt)
        listing = res.scalar_one_or_none()
        if listing:
            listing.is_verified = True
            listing.status = ListingStatus.ACTIVE
            await session.commit()
            await query.edit_message_text(f"✅ Listing #{listing_id} has been manually approved and activated.")


async def admin_disputes_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lists active disputes needing arbitration."""
    query = update.callback_query
    await query.answer()

    async with async_session_factory() as session:
        stmt = (
            select(EscrowTransaction, MarketplaceListing)
            .join(MarketplaceListing, MarketplaceListing.id == EscrowTransaction.listing_id)
            .where(EscrowTransaction.status == EscrowStatus.DISPUTED)
        )
        res = await session.execute(stmt)
        disputes = res.all()

    if not disputes:
        await query.edit_message_text(
            "✅ No active disputes.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="nav_admin")]]),
        )
        return

    text = f"⚖️ <b>Active Escrow Disputes ({len(disputes)}):</b>\n\n"
    buttons = []
    for escrow, listing in disputes:
        text += (
            f"• <b>{escrow.escrow_reference}</b> (${escrow.amount_usd:.2f})\n"
            f"  Account: {listing.platform.value} <code>{listing.account_handle}</code>\n"
            f"  Reason: <i>{escrow.dispute_reason}</i>\n\n"
        )
        buttons.append([
            InlineKeyboardButton(f"Arbitrate {escrow.escrow_reference}", callback_data=f"adm_arb:{escrow.escrow_reference}")
        ])

    buttons.append([InlineKeyboardButton("« Back", callback_data="nav_admin")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)


async def admin_arbitrate_deal_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    escrow_ref = query.data.split(":")[1]
    async with async_session_factory() as session:
        stmt = (
            select(EscrowTransaction, MarketplaceListing)
            .join(MarketplaceListing, MarketplaceListing.id == EscrowTransaction.listing_id)
            .where(EscrowTransaction.escrow_reference == escrow_ref)
        )
        res = await session.execute(stmt)
        row = res.first()

    if not row:
        await query.edit_message_text("Dispute not found.")
        return

    escrow, listing = row
    text = (
        f"⚖️ <b>Arbitrating Deal <code>{escrow.escrow_reference}</code></b>\n\n"
        f"• Amount: <b>${escrow.amount_usd:.2f}</b>\n"
        f"• Platform: {listing.platform.value} <code>{listing.account_handle}</code>\n"
        f"• Dispute Reason: <i>{escrow.dispute_reason}</i>\n\n"
        "Choose resolution action:"
    )
    await query.edit_message_text(text, reply_markup=admin_dispute_keyboard(escrow_ref), parse_mode=ParseMode.HTML)


async def admin_resolve_dispute_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":")
    escrow_ref = parts[1]
    resolution = parts[2]

    success, msg = await escrow_state_machine.resolve_dispute(
        escrow_ref=escrow_ref,
        resolution=resolution,
        admin_notes="Resolved via Telegram Admin Panel",
    )

    await query.edit_message_text(f"⚖️ <b>Dispute Resolution:</b>\n\n{msg}", parse_mode=ParseMode.HTML)


async def admin_trigger_poll_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually triggers the Celery polling worker task."""
    query = update.callback_query
    await query.answer()

    await query.edit_message_text("⚡ Triggering social media polling worker task...")
    try:
        task = poll_all_social_sources.delay()
        await query.edit_message_text(f"⚡ Polling task dispatched to Celery! Task ID: <code>{task.id}</code>", parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Error dispatching Celery task: {e}")
        await query.edit_message_text(f"❌ Failed to dispatch task: {e}")

