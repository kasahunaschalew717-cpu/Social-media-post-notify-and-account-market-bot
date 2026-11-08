import asyncio
from datetime import datetime, timedelta
from typing import List
from celery.utils.log import get_task_logger
from sqlalchemy import select
from telegram import Bot

from core.config import settings
from core.database import async_session_factory
from models.monitored_source import MonitoredSource, PlatformType
from models.listing import MarketplaceListing, ListingStatus
from models.verification import OwnershipVerification, VerificationStatus
from models.escrow import EscrowTransaction, EscrowStatus
from services.youtube import youtube_monitor
from services.telegram import telegram_monitor
from services.tiktok import tiktok_monitor
from services.instagram import instagram_monitor
from services.facebook import facebook_monitor
from services.notifier import notification_dispatcher
from marketplace.verification import verification_service
from workers.celery_app import celery_app

logger = get_task_logger(__name__)


def run_async(coro):
    """Utility to run an async coroutine inside a synchronous Celery task."""
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(name="workers.tasks.poll_all_social_sources")
def poll_all_social_sources():
    """Polls all registered sources for new posts across supported platforms."""
    logger.info("Starting periodic poll of active social sources...")
    return run_async(_async_poll_sources())


async def _async_poll_sources():
    async with async_session_factory() as session:
        stmt = select(MonitoredSource).where(MonitoredSource.is_active == True)
        res = await session.execute(stmt)
        sources: List[MonitoredSource] = res.scalars().all()

    total_sources = len(sources)
    new_posts_found = 0
    logger.info(f"Found {total_sources} active sources to poll.")

    for source in sources:
        try:
            posts = []
            if source.platform == PlatformType.TELEGRAM:
                posts = await telegram_monitor.fetch_latest_posts(source.source_id, source.last_seen_post_id)
            elif source.platform == PlatformType.TIKTOK:
                posts = await tiktok_monitor.fetch_latest_posts(source.source_id, source.last_seen_post_id)
            elif source.platform == PlatformType.INSTAGRAM:
                posts = await instagram_monitor.fetch_latest_posts(source.source_id, source.last_seen_post_id)
            elif source.platform == PlatformType.FACEBOOK:
                posts = await facebook_monitor.fetch_latest_posts(source.source_id, source.last_seen_post_id)
            elif source.platform == PlatformType.YOUTUBE:
                posts = await youtube_monitor.fetch_latest_posts(source.source_id, source.last_seen_post_id)

            for post in posts:
                delivered = await notification_dispatcher.dispatch_post(source.id, post)
                if delivered > 0:
                    new_posts_found += 1

            # Small delay between source polling to prevent upstream rate limiting
            await asyncio.sleep(1.0)

        except Exception as e:
            logger.error(f"Error polling source #{source.id} ({source.platform.value}:{source.handle}): {e}")

    logger.info(f"Polling cycle complete. Dispatched {new_posts_found} new alerts.")
    return new_posts_found


@celery_app.task(name="workers.tasks.check_pending_ownership_verifications")
def check_pending_ownership_verifications():
    """Re-checks pending ownership challenges in the background."""
    logger.info("Checking pending ownership verifications...")
    return run_async(_async_check_verifications())


async def _async_check_verifications():
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    async with async_session_factory() as session:
        stmt = (
            select(OwnershipVerification, MarketplaceListing)
            .join(MarketplaceListing, MarketplaceListing.id == OwnershipVerification.listing_id)
            .where(
                OwnershipVerification.status == VerificationStatus.PENDING,
                OwnershipVerification.verification_attempts < 10,
            )
        )
        res = await session.execute(stmt)
        pending_items = res.all()

    logger.info(f"Found {len(pending_items)} pending verifications to inspect.")

    verified_count = 0
    for verif, listing in pending_items:
        try:
            success, msg = await verification_service.check_challenge(verif.id)
            if success:
                verified_count += 1
                # Notify Seller
                try:
                    await bot.send_message(
                        chat_id=listing.seller.telegram_id,
                        text=(
                            f"🎉 <b>Ownership Verified!</b>\n\n"
                            f"Your listing for <b>{listing.platform.value}</b> (<code>{listing.account_handle}</code>) "
                            f"has been successfully verified and is now live in <b>/market</b>!"
                        ),
                        parse_mode="HTML",
                    )
                except Exception as e:
                    logger.error(f"Failed to notify seller #{listing.seller_id}: {e}")

            await asyncio.sleep(1.5)
        except Exception as e:
            logger.error(f"Error checking verification #{verif.id}: {e}")

    return verified_count


@celery_app.task(name="workers.tasks.check_escrow_inspection_timeouts")
def check_escrow_inspection_timeouts():
    """Monitors 48-72h inspection deadlines and cooling-off timers."""
    logger.info("Checking escrow inspection deadlines...")
    return run_async(_async_check_escrow_timeouts())


async def _async_check_escrow_timeouts():
    now = datetime.utcnow()
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)

    async with async_session_factory() as session:
        # Check deals awaiting inspection where deadline passed
        stmt = (
            select(EscrowTransaction)
            .where(
                EscrowTransaction.status == EscrowStatus.BUYER_CONFIRMATION_PENDING,
                EscrowTransaction.inspection_deadline <= now,
            )
        )
        res = await session.execute(stmt)
        expired_inspection_deals = res.scalars().all()

        for escrow in expired_inspection_deals:
            # Auto-complete deal if buyer never raised a dispute within the 48-72h inspection window
            escrow.status = EscrowStatus.COMPLETED
            escrow.listing.status = ListingStatus.SOLD
            escrow.seller.total_completed_deals += 1

            try:
                await bot.send_message(
                    chat_id=escrow.seller.telegram_id,
                    text=(
                        f"✅ <b>Escrow Auto-Released!</b>\n\n"
                        f"The 48-hour inspection window for deal <code>{escrow.escrow_reference}</code> has concluded "
                        f"without dispute. Payout of <b>${escrow.seller_receives_usd:.2f}</b> has been credited."
                    ),
                    parse_mode="HTML",
                )
                await bot.send_message(
                    chat_id=escrow.buyer.telegram_id,
                    text=(
                        f"ℹ️ <b>Escrow Finalized:</b> The inspection window for deal <code>{escrow.escrow_reference}</code> "
                        f"has closed. The transaction is marked completed."
                    ),
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.error(f"Error sending timeout notification: {e}")

        await session.commit()
        return len(expired_inspection_deals)


@celery_app.task(name="workers.tasks.expire_stale_listings")
def expire_stale_listings():
    """Removes listings older than 30 days without activity."""
    return run_async(_async_expire_listings())


async def _async_expire_listings():
    expiry_cutoff = datetime.utcnow() - timedelta(days=settings.LISTING_EXPIRY_DAYS)
    async with async_session_factory() as session:
        stmt = (
            select(MarketplaceListing)
            .where(
                MarketplaceListing.created_at <= expiry_cutoff,
                MarketplaceListing.status.in_([ListingStatus.ACTIVE, ListingStatus.PENDING_VERIFICATION]),
            )
        )
        res = await session.execute(stmt)
        stale_listings = res.scalars().all()

        for l in stale_listings:
            l.status = ListingStatus.EXPIRED

        await session.commit()
        logger.info(f"Marked {len(stale_listings)} listings as EXPIRED due to 30-day inactivity.")
        return len(stale_listings)

