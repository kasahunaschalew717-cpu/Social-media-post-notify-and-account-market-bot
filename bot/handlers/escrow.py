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
from sqlalchemy import select, or_

from core.config import settings
from core.logger import logger
from core.database import async_session_factory
from models.escrow import EscrowTransaction, EscrowStatus
from models.listing import MarketplaceListing
from models.user import User
from bot.states import EscrowState
from bot.keyboards import escrow_buyer_keyboard, escrow_seller_keyboard
from marketplace.escrow import escrow_state_machine
from marketplace.credentials import credential_vault
from bot.handlers.start import get_or_create_user


async def escrow_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays active escrow transactions for current user."""
    tg_user = update.effective_user
    db_user = await get_or_create_user(tg_user.id, tg_user.username, tg_user.first_name)

    async with async_session_factory() as session:
        stmt = (
            select(EscrowTransaction, MarketplaceListing)
            .join(MarketplaceListing, MarketplaceListing.id == EscrowTransaction.listing_id)
            .where(
                or_(
                    EscrowTransaction.buyer_id == db_user.id,
                    EscrowTransaction.seller_id == db_user.id,
                )
            )
            .order_by(EscrowTransaction.created_at.desc())
        )
        res = await session.execute(stmt)
        deals = res.all()

    if not deals:
        msg = "You have no active escrow transactions.\nBrowse /market to purchase or /sell to list an account."
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(msg)
        else:
            await update.message.reply_text(msg)
        return

    text = "🤝 <b>Your Escrow Transactions:</b>\n\n"
    buttons = []
    for escrow, listing in deals:
        role = "Buyer" if escrow.buyer_id == db_user.id else "Seller"
        text += (
            f"• <b>{escrow.escrow_reference}</b> ({role})\n"
            f"  Account: {listing.platform.value} <code>{listing.account_handle}</code>\n"
            f"  Amount: ${escrow.amount_usd:.2f} | Status: <code>{escrow.status.value}</code>\n\n"
        )
        buttons.append([
            InlineKeyboardButton(f"Manage {escrow.escrow_reference}", callback_data=f"escrow_status:{escrow.escrow_reference}")
        ])

    buttons.append([InlineKeyboardButton("🏠 Main Menu", callback_data="nav_main")])
    kb = InlineKeyboardMarkup(buttons)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


async def escrow_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays detailed deal state card and action buttons."""
    query = update.callback_query
    await query.answer()

    escrow_ref = query.data.split(":")[1]
    tg_user = update.effective_user
    db_user = await get_or_create_user(tg_user.id, tg_user.username, tg_user.first_name)

    async with async_session_factory() as session:
        stmt = (
            select(EscrowTransaction, MarketplaceListing)
            .join(MarketplaceListing, MarketplaceListing.id == EscrowTransaction.listing_id)
            .where(EscrowTransaction.escrow_reference == escrow_ref)
        )
        res = await session.execute(stmt)
        row = res.first()

    if not row:
        await query.edit_message_text("Escrow transaction not found.")
        return

    escrow, listing = row
    is_buyer = escrow.buyer_id == db_user.id
    is_seller = escrow.seller_id == db_user.id

    deadline_str = escrow.inspection_deadline.strftime("%Y-%m-%d %H:%M UTC") if escrow.inspection_deadline else "N/A"

    card = (
        f"🤝 <b>Escrow Transaction: <code>{escrow.escrow_reference}</code></b>\n\n"
        f"• <b>Account:</b> {listing.platform.value} <code>{listing.account_handle}</code>\n"
        f"• <b>Status:</b> <code>{escrow.status.value}</code>\n"
        f"• <b>Amount:</b> ${escrow.amount_usd:.2f} USD\n"
        f"• <b>Your Role:</b> {'Buyer' if is_buyer else 'Seller'}\n"
    )

    if escrow.status == EscrowStatus.AWAITING_PAYMENT:
        card += (
            f"\n💳 <b>Deposit Address (USDT TRC-20):</b>\n<code>{escrow.payment_address}</code>\n"
            f"Reference: <code>{escrow.escrow_reference}</code>\n"
            "Waiting for buyer payment confirmation."
        )
    elif escrow.status == EscrowStatus.FUNDS_HELD:
        card += "\n💰 <b>Payment Confirmed!</b> Funds are safely held in escrow. Seller must now submit credentials."
    elif escrow.status == EscrowStatus.BUYER_CONFIRMATION_PENDING:
        card += (
            f"\n⏱️ <b>Inspection Window Active:</b>\n"
            f"Deadline: <b>{deadline_str}</b>\n"
            "Buyer has 48 hours to secure the account and verify full control."
        )
    elif escrow.status == EscrowStatus.COMPLETED:
        card += "\n🎉 <b>Deal Completed:</b> Funds released to seller. Account transfer concluded."
    elif escrow.status == EscrowStatus.DISPUTED:
        card += f"\n🚨 <b>Under Dispute:</b> Funds are frozen. Reason:\n<i>{escrow.dispute_reason}</i>"

    if is_buyer:
        kb = escrow_buyer_keyboard(escrow.escrow_reference, has_viewed_creds=escrow.is_credentials_viewed)
    elif is_seller:
        kb = escrow_seller_keyboard(escrow.escrow_reference, escrow.status.value)
    else:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="nav_escrows")]])

    await query.edit_message_text(card, reply_markup=kb, parse_mode=ParseMode.HTML)


async def view_credentials_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Securely reveals credentials to the buyer with protect_content=True."""
    query = update.callback_query
    await query.answer()

    escrow_ref = query.data.split(":")[1]
    tg_user = update.effective_user
    db_user = await get_or_create_user(tg_user.id, tg_user.username, tg_user.first_name)

    async with async_session_factory() as session:
        stmt = select(EscrowTransaction).where(EscrowTransaction.escrow_reference == escrow_ref)
        res = await session.execute(stmt)
        escrow = res.scalar_one_or_none()

        if not escrow or escrow.buyer_id != db_user.id:
            await query.edit_message_text("Unauthorized.")
            return

        plain_creds = await credential_vault.consume_credentials(
            token=escrow.one_time_view_token or "",
            encrypted_fallback=escrow.encrypted_credentials,
        )

        if not plain_creds:
            await query.edit_message_text("Credentials have already been consumed or are not yet submitted.")
            return

        escrow.is_credentials_viewed = True
        await session.commit()

    # Deliver via message with protect_content=True to block forwarding/saving
    checklist = (
        "🔐 <b>One-Time Account Credentials Received</b>\n\n"
        f"<pre>{plain_creds}</pre>\n\n"
        "🛡️ <b>MANDATORY TRANSFER CHECKLIST (Execute in order):</b>\n"
        "1. 🔑 <b>Log into the account</b> and check email/recovery settings.\n"
        "2. ✉️ <b>Change Primary Recovery Email</b> to your own email address.\n"
        "3. 📱 <b>Change Phone Number</b> to your own verified number.\n"
        "4. 🔒 <b>Update Account Password</b> immediately.\n"
        "5. 🛡️ <b>Enable Two-Factor Authentication (2FA)</b> via Google Authenticator or hardware key.\n"
        "6. 🚪 <b>Revoke all active sessions & tokens</b> in Account Settings -> Security -> Devices.\n\n"
        "⚠️ <i>Once all steps are done and verified, return to /escrow and tap 'Confirm Full Control & Release'.</i>"
    )

    await context.bot.send_message(
        chat_id=tg_user.id,
        text=checklist,
        parse_mode=ParseMode.HTML,
        protect_content=True,
    )

    await query.edit_message_text("✅ Credentials delivered privately above with content protection enabled.")


async def submit_credentials_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Starts conversation for seller submitting credentials."""
    query = update.callback_query
    await query.answer()

    escrow_ref = query.data.split(":")[1]
    context.user_data["active_escrow_ref"] = escrow_ref

    prompt = (
        f"🔐 <b>Submit Account Credentials for Deal <code>{escrow_ref}</code></b>\n\n"
        "Please send the login credentials for the buyer.\n\n"
        "<i>Include:</i>\n"
        "• Username / Login email\n"
        "• Password\n"
        "• 2FA Backup codes (if enabled)\n"
        "• Linked email credentials (if included)\n\n"
        "<i>Your credentials will be encrypted with AES-GCM and delivered via a self-destructing one-time token.</i>"
    )
    await query.edit_message_text(prompt, parse_mode=ParseMode.HTML)
    return EscrowState.SUBMIT_CREDENTIALS


async def submit_credentials_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processes submitted credentials, encrypts and notifies buyer."""
    raw_creds = update.message.text.strip()
    escrow_ref = context.user_data.get("active_escrow_ref")

    if not escrow_ref:
        await update.message.reply_text("Session timed out. Please send /escrow again.")
        return ConversationHandler.END

    tg_user = update.effective_user
    db_user = await get_or_create_user(tg_user.id, tg_user.username, tg_user.first_name)

    success, msg, token = await escrow_state_machine.submit_transfer_credentials(
        escrow_ref=escrow_ref,
        seller_user_id=db_user.id,
        raw_credentials=raw_creds,
    )

    if not success:
        await update.message.reply_text(f"❌ Error submitting credentials: {msg}")
        return ConversationHandler.END

    # Delete the message containing sensitive credentials from chat history for safety
    try:
        await update.message.delete()
    except Exception:
        pass

    await update.message.reply_text(
        f"✅ <b>Credentials Encrypted & Transferred!</b>\n\n"
        f"The buyer has been notified to inspect and take control of the account. "
        f"The 48-hour inspection window is now running.\n"
        f"Deal reference: <code>{escrow_ref}</code>",
        parse_mode=ParseMode.HTML,
    )

    # Notify Buyer via Telegram
    async with async_session_factory() as session:
        stmt = select(EscrowTransaction).where(EscrowTransaction.escrow_reference == escrow_ref)
        res = await session.execute(stmt)
        escrow = res.scalar_one_or_none()
        if escrow and escrow.buyer:
            try:
                await context.bot.send_message(
                    chat_id=escrow.buyer.telegram_id,
                    text=(
                        f"🔑 <b>Credentials Ready for Deal <code>{escrow_ref}</code>!</b>\n\n"
                        "The seller has deposited the account credentials in the encrypted vault.\n"
                        "Tap /escrow -> 'View One-Time Credentials' to reveal them and begin the transfer checklist."
                    ),
                    parse_mode=ParseMode.HTML,
                )
            except Exception as e:
                logger.error(f"Failed to notify buyer: {e}")

    return ConversationHandler.END


async def buyer_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Buyer confirms full control and releases funds."""
    query = update.callback_query
    await query.answer()

    escrow_ref = query.data.split(":")[1]
    tg_user = update.effective_user
    db_user = await get_or_create_user(tg_user.id, tg_user.username, tg_user.first_name)

    success, msg = await escrow_state_machine.confirm_buyer_ownership(escrow_ref, db_user.id)

    if success:
        await query.edit_message_text(f"🎉 <b>Success!</b>\n\n{msg}", parse_mode=ParseMode.HTML)
    else:
        await query.edit_message_text(f"⚠️ {msg}", parse_mode=ParseMode.HTML)


async def dispute_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Starts dispute filing."""
    query = update.callback_query
    await query.answer()

    escrow_ref = query.data.split(":")[1]
    context.user_data["dispute_escrow_ref"] = escrow_ref

    await query.edit_message_text(
        f"🚨 <b>Raise Dispute for Deal <code>{escrow_ref}</code></b>\n\n"
        "Please provide a detailed explanation of the issue (e.g., invalid credentials, "
        "seller attempting recovery, account suspended, etc.):",
        parse_mode=ParseMode.HTML,
    )
    return EscrowState.ENTER_DISPUTE_REASON


async def dispute_reason_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Freezes escrow and alerts admins."""
    reason = update.message.text.strip()
    escrow_ref = context.user_data.get("dispute_escrow_ref")

    if not escrow_ref:
        await update.message.reply_text("Session timed out.")
        return ConversationHandler.END

    tg_user = update.effective_user
    db_user = await get_or_create_user(tg_user.id, tg_user.username, tg_user.first_name)

    success, msg = await escrow_state_machine.raise_dispute(
        escrow_ref=escrow_ref,
        user_id=db_user.id,
        reason=reason,
    )

    if success:
        await update.message.reply_text(
            f"🚨 <b>Dispute Filed:</b>\n\n{msg}\n\n"
            f"Deal: <code>{escrow_ref}</code>\n"
            "Staff has been alerted. Please keep all evidence and transaction records.",
            parse_mode=ParseMode.HTML,
        )
        # Notify admins
        for admin_id in settings.ADMIN_USER_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=(
                        f"🚨 <b>DISPUTE ALERT!</b>\n\n"
                        f"Escrow: <code>{escrow_ref}</code>\n"
                        f"Raised by User: @{tg_user.username} ({tg_user.id})\n"
                        f"Reason:\n<i>{reason}</i>\n\n"
                        "Check /admin to arbitrate."
                    ),
                    parse_mode=ParseMode.HTML,
                )
            except Exception as e:
                logger.error(f"Failed to alert admin {admin_id}: {e}")
    else:
        await update.message.reply_text(f"❌ {msg}")

    return ConversationHandler.END


def get_escrow_credential_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(submit_credentials_start, pattern="^submit_creds:"),
        ],
        states={
            EscrowState.SUBMIT_CREDENTIALS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, submit_credentials_received),
            ],
        },
        fallbacks=[CommandHandler("cancel", escrow_list_command)],
        per_user=True,
    )


def get_escrow_dispute_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(dispute_start_callback, pattern="^raise_dispute:"),
        ],
        states={
            EscrowState.ENTER_DISPUTE_REASON: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, dispute_reason_received),
            ],
        },
        fallbacks=[CommandHandler("cancel", escrow_list_command)],
        per_user=True,
    )

