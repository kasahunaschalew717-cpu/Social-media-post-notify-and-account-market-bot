import asyncio
from datetime import datetime
from core.database import async_session_factory
from core.logger import logger
from models import (
    User,
    UserRole,
    MonitoredSource,
    PlatformType,
    Subscription,
    MarketplaceListing,
    ListingStatus,
    OwnershipVerification,
    VerificationStatus,
    VerificationMethod,
)


async def seed_demo_data():
    """Seeds sample data for local testing of alerts and verified marketplace."""
    logger.info("Seeding demo database records...")

    async with async_session_factory() as session:
        # 1. Create Demo Users
        admin_user = User(
            telegram_id=111111111,
            username="admin_user",
            first_name="Platform Admin",
            role=UserRole.ADMIN,
            reputation_score=5.0,
            total_completed_deals=25,
        )
        seller_user = User(
            telegram_id=222222222,
            username="verified_seller",
            first_name="Alex Seller",
            role=UserRole.USER,
            reputation_score=4.9,
            total_completed_deals=12,
        )
        buyer_user = User(
            telegram_id=333333333,
            username="crypto_buyer",
            first_name="Sam Buyer",
            role=UserRole.USER,
            reputation_score=5.0,
            total_completed_deals=3,
        )
        session.add_all([admin_user, seller_user, buyer_user])
        await session.commit()

        # 2. Create Monitored Sources (Creator Alert Engine)
        yt_source = MonitoredSource(
            platform=PlatformType.YOUTUBE,
            handle="@mkbhd",
            source_id="UCBJycsmduvYEL83R_U4JriQ",
            display_name="Marques Brownlee",
            url="https://www.youtube.com/@mkbhd",
            is_active=True,
        )
        tg_source = MonitoredSource(
            platform=PlatformType.TELEGRAM,
            handle="@durov",
            source_id="durov",
            display_name="Pavel Durov",
            url="https://t.me/durov",
            is_active=True,
        )
        tiktok_source = MonitoredSource(
            platform=PlatformType.TIKTOK,
            handle="@khaby.lame",
            source_id="khaby.lame",
            display_name="Khaby Lame",
            url="https://www.tiktok.com/@khaby.lame",
            is_active=True,
        )
        session.add_all([yt_source, tg_source, tiktok_source])
        await session.commit()

        # 3. Create Subscriptions
        sub1 = Subscription(user_id=buyer_user.id, source_id=yt_source.id)
        sub2 = Subscription(user_id=buyer_user.id, source_id=tg_source.id)
        session.add_all([sub1, sub2])

        # 4. Create Verified Marketplace Listings
        listing1 = MarketplaceListing(
            seller_id=seller_user.id,
            platform=PlatformType.YOUTUBE,
            account_handle="@TechDailyHub",
            asking_price_usd=350.00,
            follower_count=45000,
            niche="Tech",
            description="Established tech tutorials channel with 45k organic subs. Original email included. Monetization enabled.",
            status=ListingStatus.ACTIVE,
            is_verified=True,
            verified_at=datetime.utcnow(),
        )
        listing2 = MarketplaceListing(
            seller_id=seller_user.id,
            platform=PlatformType.TELEGRAM,
            account_handle="@CryptoSignalsDaily",
            asking_price_usd=850.00,
            follower_count=18000,
            niche="Crypto",
            description="High-engagement crypto community channel. 18k active members, 30% view rate. Creator ownership verified.",
            status=ListingStatus.ACTIVE,
            is_verified=True,
            verified_at=datetime.utcnow(),
        )
        listing3 = MarketplaceListing(
            seller_id=seller_user.id,
            platform=PlatformType.TIKTOK,
            account_handle="@FitnessGainsDaily",
            asking_price_usd=180.00,
            follower_count=62000,
            niche="Lifestyle",
            description="Fitness motivational short videos. 62k followers, high engagement. Clean history, no community strikes.",
            status=ListingStatus.ACTIVE,
            is_verified=True,
            verified_at=datetime.utcnow(),
        )
        session.add_all([listing1, listing2, listing3])
        await session.commit()

        # 5. Add Verification Records
        v1 = OwnershipVerification(
            listing_id=listing1.id,
            challenge_code="VERIFY-8K9P2X",
            method=VerificationMethod.BIO_CODE,
            status=VerificationStatus.VERIFIED,
            details="Challenge code found in channel description.",
        )
        v2 = OwnershipVerification(
            listing_id=listing2.id,
            challenge_code="VERIFY-4M7L1Q",
            method=VerificationMethod.BOT_ADMIN_CHECK,
            status=VerificationStatus.VERIFIED,
            details="Bot verified as temporary administrator with post permissions.",
        )
        session.add_all([v1, v2])
        await session.commit()

    logger.info("Demo data seeded successfully!")


if __name__ == "__main__":
    asyncio.run(seed_demo_data())

