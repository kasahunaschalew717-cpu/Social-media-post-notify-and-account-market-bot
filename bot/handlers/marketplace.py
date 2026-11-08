from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler
from sqlalchemy import select, and_, func

from core.config import settings
from core.logger import logger
from core.database import async_session_factory
from models.monitored_source import PlatformType
from models.listing import MarketplaceListing, ListingStatus
from models.user import User
from bot.keyboards import market_filter_keyboard, listing_detail_keyboard
from marketplace.escrow import escrow_state_machine
from bot.handlers.start import get_or_create_user

ITEMS_PER_PAGE = 3


async def market_catalog_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the verified marketplace catalog."""
    page = context.user_data.get("market_page", 1)
    platform_filter = context.user_data.get("market_plat_filter", "ALL")

    await render_market_catalog(update, context, page=page, platform=platform_filter)


async def render_market_catalog(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1, platform: str = "ALL"):
    offset = (page - 1) * ITEMS_PER_PAGE

    async with async_session_factory() as session:
        # Base condition: Only verified active listings
        conditions = [
            MarketplaceListing.status == ListingStatus.ACTIVE,
            MarketplaceListing.is_verified == True,
        ]
        if platform != "ALL":
            conditions.append(MarketplaceListing.platform == PlatformType(platform))

        # Count total
        count_stmt = select(func.count(MarketplaceListing.id)).where(and_(*conditions))
        total_count = (await session.execute(count_stmt)).scalar() or 0
        total_pages = max(1, (total_count + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)

        # Fetch page items
        stmt = (
            select(MarketplaceListing, User)
            .join(User, User.id == MarketplaceListing.seller_id)
            .where(and_(*conditions))
            .order_by(MarketplaceListing.created_at.desc())
            .offset(offset)
            .limit(ITEMS_PER_PAGE)
        )
        res = await session.execute(stmt)
        listings = res.all()

    if not listings:
        text = (
            "🛒 <b>Verified Social Account Marketplace</b>\n\n"
            f"No verified listings found matching filter: <b>{platform}</b>.\n"
            "Be the first to list! Send /sell to list your account."
        )
        kb = market_filter_keyboard(current_platform=platform, page=1, total_pages=1)
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        return

    text = (
        "🛒 <b>Verified Social Account Marketplace</b>\n"
        f"Showing {len(listings)} of {total_count} active listings (Page {page}/{total_pages})\n"
        "<i>All listings are ownership-verified and transactions protected by platform escrow.</i>\n\n"
    )

    buttons = []
    for listing, seller in listings:
        verif_date = listing.verified_at.strftime("%Y-%m-%d") if listing.verified_at else "Verified"
        text += (
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"<b>{listing.platform.value}</b>: <code>{listing.account_handle}</code>\n"
            f"💰 <b>Price:</b> ${listing.asking_price_usd:.2f}\n"
            f"👥 <b>Followers:</b> {listing.follower_count:,} | 🏷️ <b>Niche:</b> {listing.niche}\n"
            f"✅ <i>Ownership Verified on {verif_date}</i>\n"
            f"⭐ Seller Rating: {seller.reputation_score:.1f}/5.0 ({seller.total_completed_deals} deals)\n"
            f"📝 <i>{listing.description[:120]}...</i>\n\n"
        )
        buttons.append([
            InlineKeyboardButton(
                f"💳 Buy {listing.platform.value} {listing.account_handle} (${listing.asking_price_usd:.0f})",
                callback_data=f"buy_listing:{listing.id}",
            )
        ])

    # Add filter and pagination toolbar
    toolbar = market_filter_keyboard(current_platform=platform, page=page, total_pages=total_pages)
    for row in toolbar.inline_keyboard:
        buttons.append(row)

    kb = InlineKeyboardMarkup(buttons)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


async def market_pagination_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data.split(":")
    page = int(data[1])
    context.user_data["market_page"] = page
    platform = context.user_data.get("market_plat_filter", "ALL")

    await render_market_catalog(update, context, page=page, platform=platform)


async def market_filter_platform_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cycles through platforms or shows platform selection for filtering."""
    query = update.callback_query
    await query.answer()

    # Platforms list
    platforms = ["ALL", "YOUTUBE", "TELEGRAM", "TIKTOK", "INSTAGRAM", "FACEBOOK"]
    current = context.user_data.get("market_plat_filter", "ALL")
    next_idx = (platforms.index(current) + 1) % len(platforms)
    context.user_data["market_plat_filter"] = platforms[next_idx]
    context.user_data["market_page"] = 1

    await render_market_catalog(update, context, page=1, platform=platforms[next_idx])


async def buy_listing_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Initiates an escrow transaction when a buyer clicks 'Buy'."""
    query = update.callback_query
    await query.answer()

    listing_id = int(query.data.split(":")[1])
    tg_user = update.effective_user
    db_user = await get_or_create_user(tg_user.id, tg_user.username, tg_user.first_name)

    escrow, msg = await escrow_state_machine.create_escrow(listing_id=listing_id, buyer_user_id=db_user.id)

    if not escrow:
        await query.edit_message_text(f"❌ <b>Could not initiate deal:</b> {msg}", parse_mode=ParseMode.HTML)
        return

    invoice_text = (
        f"🤝 <b>Escrow Deal Created: <code>{escrow.escrow_reference}</code></b>\n\n"
        f"Account: <b>{escrow.listing.platform.value}</b> (<code>{escrow.listing.account_handle}</code>)\n"
        f"Amount: <b>${escrow.amount_usd:.2f} USD</b>\n"
        f"Platform Escrow Fee: <b>${escrow.fee_usd:.2f}</b> (included)\n\n"
        "💳 <b>Payment Instructions:</b>\n"
        f"Deposit Address (USDT TRC-20):\n<code>{escrow.payment_address}</code>\n\n"
        f"Payment Memo / Reference:\n<code>{escrow.escrow_reference}</code>\n\n"
        "⚠️ <i>Funds are locked in platform escrow. Once your deposit confirms, "
        "the seller will transfer credentials to the encrypted vault.</i>\n\n"
        "Tap /escrow anytime to track this deal."
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh Payment Status", callback_data=f"escrow_status:{escrow.escrow_reference}")],
        [InlineKeyboardButton("❌ Cancel Deal", callback_data=f"cancel_escrow:{escrow.escrow_reference}")],
    ])

    await query.edit_message_text(invoice_text, reply_markup=kb, parse_mode=ParseMode.HTML)

