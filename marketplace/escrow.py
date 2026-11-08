from datetime import datetime, timedelta
from typing import Optional, Tuple
from sqlalchemy import select
from core.config import settings
from core.logger import logger
from core.security import generate_verification_code
from core.database import async_session_factory
from models.listing import MarketplaceListing, ListingStatus
from models.user import User
from models.escrow import EscrowTransaction, EscrowStatus
from marketplace.credentials import credential_vault


class EscrowStateMachine:
    """
    Manages the lifecycle and state transitions of social account transactions.
    Enforces a strict, fraud-resistant escrow workflow:
    AWAITING_PAYMENT -> FUNDS_HELD -> TRANSFER_IN_PROGRESS -> BUYER_CONFIRMATION_PENDING -> COMPLETED
    """

    async def create_escrow(self, listing_id: int, buyer_user_id: int) -> Tuple[Optional[EscrowTransaction], str]:
        """
        Initiates an escrow transaction when a buyer clicks 'Buy'.
        """
        async with async_session_factory() as session:
            stmt = select(MarketplaceListing).where(MarketplaceListing.id == listing_id)
            res = await session.execute(stmt)
            listing = res.scalar_one_or_none()

            if not listing:
                return None, "Listing not found."

            if listing.status != ListingStatus.ACTIVE or not listing.is_verified:
                return None, "Listing is not active or has not passed ownership verification."

            if listing.seller_id == buyer_user_id:
                return None, "You cannot purchase your own listing."

            # Calculate escrow fees
            amount = float(listing.asking_price_usd)
            fee = round(amount * (settings.PLATFORM_ESCROW_FEE_PERCENT / 100.0), 2)
            seller_receives = round(amount - fee, 2)

            # Generate reference: e.g. ESCROW-7X9K2A
            code = generate_verification_code(8)
            escrow_ref = f"ESCROW-{code.split('-')[1]}"

            escrow = EscrowTransaction(
                escrow_reference=escrow_ref,
                listing_id=listing.id,
                buyer_id=buyer_user_id,
                seller_id=listing.seller_id,
                amount_usd=amount,
                fee_usd=fee,
                seller_receives_usd=seller_receives,
                status=EscrowStatus.AWAITING_PAYMENT,
                payment_address=settings.ESCROW_PAYMENT_WALLET_USDT_TRC20,
            )

            # Lock listing
            listing.status = ListingStatus.IN_ESCROW

            session.add(escrow)
            await session.commit()
            await session.refresh(escrow)

            logger.info(f"Created escrow {escrow.escrow_reference} for listing #{listing.id} by buyer {buyer_user_id}")
            return escrow, "Escrow created successfully."

    async def confirm_payment(self, escrow_ref: str, tx_hash: Optional[str] = None) -> Tuple[bool, str]:
        """
        Transitions state from AWAITING_PAYMENT to FUNDS_HELD.
        Triggered when payment is confirmed via gateway webhook or admin confirmation.
        """
        async with async_session_factory() as session:
            stmt = select(EscrowTransaction).where(EscrowTransaction.escrow_reference == escrow_ref)
            res = await session.execute(stmt)
            escrow = res.scalar_one_or_none()

            if not escrow:
                return False, "Escrow transaction not found."

            if escrow.status != EscrowStatus.AWAITING_PAYMENT:
                return False, f"Invalid state transition: Current status is {escrow.status.value}"

            escrow.status = EscrowStatus.FUNDS_HELD
            escrow.payment_tx_hash = tx_hash or "CONFIRMED_BY_GATEWAY"
            await session.commit()

            logger.info(f"Funds held for escrow {escrow_ref}. Seller must now provide credentials.")
            return True, "Payment confirmed. Funds are securely locked in platform escrow."

    async def submit_transfer_credentials(
        self,
        escrow_ref: str,
        seller_user_id: int,
        raw_credentials: str,
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Seller submits account credentials.
        Encrypted and stored in credential vault.
        Transitions to BUYER_CONFIRMATION_PENDING and starts 48-72h inspection timer.
        """
        async with async_session_factory() as session:
            stmt = select(EscrowTransaction).where(EscrowTransaction.escrow_reference == escrow_ref)
            res = await session.execute(stmt)
            escrow = res.scalar_one_or_none()

            if not escrow:
                return False, "Escrow not found.", None

            if escrow.seller_id != seller_user_id:
                return False, "Unauthorized: Only the seller can submit credentials.", None

            if escrow.status != EscrowStatus.FUNDS_HELD:
                return False, f"Cannot submit credentials in state: {escrow.status.value}", None

            # Encrypt and store
            token, ciphertext = await credential_vault.store_credentials(raw_credentials, escrow_ref)
            escrow.encrypted_credentials = ciphertext
            escrow.one_time_view_token = token
            escrow.status = EscrowStatus.BUYER_CONFIRMATION_PENDING
            escrow.inspection_deadline = datetime.utcnow() + timedelta(hours=settings.INSPECTION_WINDOW_HOURS)

            # High value cooling-off calculation
            if float(escrow.amount_usd) >= settings.HIGH_VALUE_THRESHOLD_USD:
                escrow.cooling_off_until = datetime.utcnow() + timedelta(days=settings.COOLING_OFF_PERIOD_DAYS)

            await session.commit()
            logger.info(f"Seller provided credentials for {escrow_ref}. Inspection window initiated.")
            return True, "Credentials submitted securely.", token

    async def confirm_buyer_ownership(
        self,
        escrow_ref: str,
        buyer_user_id: int,
    ) -> Tuple[bool, str]:
        """
        Buyer confirms successful handover, email change, and 2FA setup.
        Releases funds to seller (unless high-value cooling-off applies).
        """
        async with async_session_factory() as session:
            stmt = (
                select(EscrowTransaction, MarketplaceListing, User)
                .join(MarketplaceListing, MarketplaceListing.id == EscrowTransaction.listing_id)
                .join(User, User.id == EscrowTransaction.seller_id)
                .where(EscrowTransaction.escrow_reference == escrow_ref)
            )
            res = await session.execute(stmt)
            row = res.first()

            if not row:
                return False, "Escrow transaction not found."

            escrow, listing, seller = row

            if escrow.buyer_id != buyer_user_id:
                return False, "Unauthorized: Only the buyer can confirm ownership."

            if escrow.status != EscrowStatus.BUYER_CONFIRMATION_PENDING:
                return False, f"Cannot confirm ownership in current state: {escrow.status.value}"

            # High value cooling-off check
            now = datetime.utcnow()
            if escrow.cooling_off_until and now < escrow.cooling_off_until:
                remaining_days = (escrow.cooling_off_until - now).days + 1
                return False, (
                    f"🛡️ High-Value Account Protection: This account has a {settings.COOLING_OFF_PERIOD_DAYS}-day "
                    f"cooling-off period to prevent recovery scams. Payout will release in {remaining_days} days."
                )

            # Complete transaction
            escrow.status = EscrowStatus.COMPLETED
            listing.status = ListingStatus.SOLD

            # Update seller stats
            seller.total_completed_deals += 1

            await session.commit()
            logger.info(f"Escrow {escrow_ref} COMPLETED. Payout of ${escrow.seller_receives_usd} released to seller #{seller.id}")
            return True, f"🎉 Transaction Completed! Funds of ${escrow.seller_receives_usd:.2f} released to seller."

    async def raise_dispute(
        self,
        escrow_ref: str,
        user_id: int,
        reason: str,
    ) -> Tuple[bool, str]:
        """
        Buyer or seller triggers a dispute. Funds are frozen and admin alerted.
        """
        async with async_session_factory() as session:
            stmt = select(EscrowTransaction).where(EscrowTransaction.escrow_reference == escrow_ref)
            res = await session.execute(stmt)
            escrow = res.scalar_one_or_none()

            if not escrow:
                return False, "Escrow transaction not found."

            if user_id not in (escrow.buyer_id, escrow.seller_id):
                return False, "Unauthorized: Only buyer or seller can dispute this deal."

            if escrow.status not in (
                EscrowStatus.FUNDS_HELD,
                EscrowStatus.TRANSFER_IN_PROGRESS,
                EscrowStatus.BUYER_CONFIRMATION_PENDING,
            ):
                return False, f"Cannot dispute an escrow in state: {escrow.status.value}"

            escrow.status = EscrowStatus.DISPUTED
            escrow.dispute_reason = reason
            escrow.disputed_at = datetime.utcnow()
            await session.commit()

            logger.warning(f"Dispute raised on escrow {escrow_ref} by user #{user_id}: {reason}")
            return True, "🚨 Dispute initiated. Funds are frozen. Platform staff has been notified for arbitration."

    async def resolve_dispute(
        self,
        escrow_ref: str,
        resolution: str,  # 'release_to_seller' or 'refund_buyer'
        admin_notes: str,
    ) -> Tuple[bool, str]:
        """
        Admin arbitration to release funds or refund buyer.
        """
        async with async_session_factory() as session:
            stmt = (
                select(EscrowTransaction, MarketplaceListing)
                .join(MarketplaceListing, MarketplaceListing.id == EscrowTransaction.listing_id)
                .where(EscrowTransaction.escrow_reference == escrow_ref)
            )
            res = await session.execute(stmt)
            row = res.first()

            if not row:
                return False, "Escrow not found."

            escrow, listing = row
            if escrow.status != EscrowStatus.DISPUTED:
                return False, f"Escrow is not in DISPUTED state (current: {escrow.status.value})"

            escrow.dispute_resolution = f"Admin Decision: {resolution}. Notes: {admin_notes}"

            if resolution == "release_to_seller":
                escrow.status = EscrowStatus.COMPLETED
                listing.status = ListingStatus.SOLD
                msg = f"Dispute resolved in favor of seller. Payout ${escrow.seller_receives_usd} released."
            elif resolution == "refund_buyer":
                escrow.status = EscrowStatus.REFUNDED
                listing.status = ListingStatus.ACTIVE  # return listing to market
                msg = f"Dispute resolved in favor of buyer. Refund of ${escrow.amount_usd} processed."
            else:
                return False, f"Unknown resolution type: {resolution}"

            await session.commit()
            logger.info(f"Dispute on {escrow_ref} resolved by admin: {resolution}")
            return True, msg

    async def cancel_escrow(self, escrow_ref: str, user_id: int) -> Tuple[bool, str]:
        """
        Cancels an unpaid escrow transaction and frees the listing.
        """
        async with async_session_factory() as session:
            stmt = (
                select(EscrowTransaction, MarketplaceListing)
                .join(MarketplaceListing, MarketplaceListing.id == EscrowTransaction.listing_id)
                .where(EscrowTransaction.escrow_reference == escrow_ref)
            )
            res = await session.execute(stmt)
            row = res.first()
            if not row:
                return False, "Escrow not found."

            escrow, listing = row
            if escrow.status != EscrowStatus.AWAITING_PAYMENT:
                return False, f"Cannot cancel transaction once funds are held (current: {escrow.status.value})"

            if user_id not in (escrow.buyer_id, escrow.seller_id):
                return False, "Unauthorized."

            escrow.status = EscrowStatus.CANCELLED
            listing.status = ListingStatus.ACTIVE
            await session.commit()

            return True, "Escrow transaction cancelled. Listing has been returned to the marketplace."


escrow_state_machine = EscrowStateMachine()

