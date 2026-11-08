import re
from datetime import datetime
from typing import Tuple, Optional
import httpx
from bs4 import BeautifulSoup
from telegram import Bot

from core.config import settings
from core.logger import logger
from core.security import generate_verification_code
from core.database import async_session_factory
from models.monitored_source import PlatformType
from models.listing import MarketplaceListing, ListingStatus
from models.verification import OwnershipVerification, VerificationMethod, VerificationStatus
from sqlalchemy import select


class OwnershipVerificationService:
    def __init__(self, bot_token: str = settings.TELEGRAM_BOT_TOKEN):
        self.bot = Bot(token=bot_token)

    def get_instructions(self, platform: PlatformType, code: str, handle: str) -> str:
        """
        Returns clear, non-forgeable challenge instructions for the seller.
        """
        lines = [
            f"🔐 <b>Ownership Verification for {platform.value} account ({handle})</b>\n",
            f"Your unique challenge code is:\n<code>{code}</code>\n",
            "<b>Instructions:</b>",
        ]

        if platform == PlatformType.TIKTOK:
            lines.extend([
                "1. Open TikTok and edit your profile bio.",
                f"2. Temporarily paste the code <code>{code}</code> into your Bio (or as caption of a new temporary video).",
                "3. Tap <b>'Verify Now'</b> below once saved.",
                "4. You can remove the code once verification succeeds.",
            ])
        elif platform == PlatformType.YOUTUBE:
            lines.extend([
                "1. Go to YouTube Studio -> Customization -> Basic Info.",
                f"2. Add <code>{code}</code> anywhere in the Channel Description.",
                "3. Alternatively, publish a Community Post containing this code.",
                "4. Tap <b>'Verify Now'</b> below.",
            ])
        elif platform == PlatformType.TELEGRAM:
            lines.extend([
                "Choose ONE of the following methods:",
                f"<b>Option A (Fastest):</b> Add this bot as an Administrator to your channel with 'Post Messages' permission temporarily.",
                f"<b>Option B:</b> Add the code <code>{code}</code> to your Channel Description or as a pinned post.",
                "Then tap <b>'Verify Now'</b>.",
            ])
        elif platform in (PlatformType.INSTAGRAM, PlatformType.FACEBOOK):
            lines.extend([
                f"1. Edit your profile bio/about section.",
                f"2. Add the verification code <code>{code}</code>.",
                "3. Tap <b>'Verify Now'</b> below.",
            ])

        return "\n".join(lines)

    async def initiate_verification(self, listing_id: int) -> Tuple[OwnershipVerification, str]:
        """Creates a pending verification challenge for a listing."""
        code = generate_verification_code()

        async with async_session_factory() as session:
            stmt = select(MarketplaceListing).where(MarketplaceListing.id == listing_id)
            res = await session.execute(stmt)
            listing = res.scalar_one_or_none()
            if not listing:
                raise ValueError("Listing not found")

            method = (
                VerificationMethod.BOT_ADMIN_CHECK
                if listing.platform == PlatformType.TELEGRAM
                else VerificationMethod.BIO_CODE
            )

            verif = OwnershipVerification(
                listing_id=listing_id,
                challenge_code=code,
                method=method,
                status=VerificationStatus.PENDING,
            )
            session.add(verif)
            listing.status = ListingStatus.PENDING_VERIFICATION
            await session.commit()
            await session.refresh(verif)

            instructions = self.get_instructions(listing.platform, code, listing.account_handle)
            return verif, instructions

    async def check_challenge(self, verification_id: int) -> Tuple[bool, str]:
        """
        Executes automated inspection of the account to detect the challenge code.
        """
        async with async_session_factory() as session:
            stmt = (
                select(OwnershipVerification, MarketplaceListing)
                .join(MarketplaceListing, MarketplaceListing.id == OwnershipVerification.listing_id)
                .where(OwnershipVerification.id == verification_id)
            )
            res = await session.execute(stmt)
            row = res.first()
            if not row:
                return False, "Verification record not found."

            verif, listing = row
            verif.verification_attempts += 1
            verif.last_checked_at = datetime.utcnow()

            is_verified = False
            detail_msg = ""

            # Check logic per platform
            if listing.platform == PlatformType.TELEGRAM:
                is_verified, detail_msg = await self._check_telegram_challenge(
                    listing.account_handle, verif.challenge_code
                )
            elif listing.platform == PlatformType.YOUTUBE:
                is_verified, detail_msg = await self._check_youtube_challenge(
                    listing.account_handle, verif.challenge_code
                )
            elif listing.platform == PlatformType.TIKTOK:
                is_verified, detail_msg = await self._check_tiktok_challenge(
                    listing.account_handle, verif.challenge_code
                )
            elif listing.platform == PlatformType.INSTAGRAM:
                is_verified, detail_msg = await self._check_instagram_challenge(
                    listing.account_handle, verif.challenge_code
                )
            elif listing.platform == PlatformType.FACEBOOK:
                is_verified, detail_msg = await self._check_facebook_challenge(
                    listing.account_handle, verif.challenge_code
                )

            if is_verified:
                verif.status = VerificationStatus.VERIFIED
                verif.details = detail_msg
                listing.is_verified = True
                listing.verified_at = datetime.utcnow()

                # High value check
                if float(listing.asking_price_usd) >= settings.HIGH_VALUE_THRESHOLD_USD:
                    # High value account requires secondary proof review
                    listing.status = ListingStatus.PENDING_VERIFICATION
                    verif.details += " (Code confirmed. Secondary live dashboard proof required for high-value accounts)."
                else:
                    listing.status = ListingStatus.ACTIVE

                await session.commit()
                return True, f"✅ Ownership Verified! {detail_msg}"
            else:
                verif.details = f"Attempt {verif.verification_attempts}: {detail_msg}"
                if verif.verification_attempts >= 10:
                    verif.status = VerificationStatus.FAILED
                    listing.status = ListingStatus.REJECTED

                await session.commit()
                return False, f"❌ Verification Challenge Not Detected.\nReason: {detail_msg}"

    async def _check_telegram_challenge(self, handle: str, code: str) -> Tuple[bool, str]:
        clean_user = handle.lstrip("@").strip()

        # Method 1: Check if bot is an admin in the channel
        try:
            bot_me = await self.bot.get_me()
            chat_member = await self.bot.get_chat_member(f"@{clean_user}", bot_me.id)
            if chat_member and chat_member.status in ("administrator", "creator"):
                return True, f"Bot is confirmed administrator with rights '{chat_member.status}'."
        except Exception as e:
            logger.debug(f"Bot admin check error for @{clean_user}: {e}")

        # Method 2: Check channel description or pinned post via web preview
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"https://t.me/s/{clean_user}")
                if resp.status_code == 200:
                    if code in resp.text:
                        return True, "Code found in public channel description or recent posts."
        except Exception as e:
            logger.debug(f"Telegram web check error: {e}")

        return False, f"Code '{code}' was not found in description or bot was not added as admin."

    async def _check_youtube_challenge(self, handle: str, code: str) -> Tuple[bool, str]:
        clean_handle = handle.lstrip("@").strip()
        url = f"https://www.youtube.com/@{clean_handle}"
        try:
            async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0"}, timeout=12.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200 and code in resp.text:
                    return True, "Code found in YouTube channel page."
        except Exception as e:
            logger.debug(f"YouTube challenge check error: {e}")
        return False, f"Code '{code}' not detected in YouTube channel description."

    async def _check_tiktok_challenge(self, handle: str, code: str) -> Tuple[bool, str]:
        clean_handle = handle.lstrip("@").strip()
        url = f"https://www.tiktok.com/@{clean_handle}"
        try:
            async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0"}, timeout=12.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200 and code in resp.text:
                    return True, "Code found in TikTok profile."
        except Exception as e:
            logger.debug(f"TikTok challenge check error: {e}")
        return False, f"Code '{code}' not found in TikTok bio. If recently updated, please wait 2 minutes for CDN refresh."

    async def _check_instagram_challenge(self, handle: str, code: str) -> Tuple[bool, str]:
        clean_handle = handle.lstrip("@").strip()
        url = f"https://www.instagram.com/{clean_handle}/"
        try:
            async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0"}, timeout=12.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200 and code in resp.text:
                    return True, "Code found in Instagram bio."
        except Exception as e:
            logger.debug(f"Instagram challenge check error: {e}")
        return False, f"Code '{code}' not detected in Instagram profile."

    async def _check_facebook_challenge(self, handle: str, code: str) -> Tuple[bool, str]:
        clean_handle = handle.lstrip("@").strip()
        url = f"https://www.facebook.com/{clean_handle}"
        try:
            async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0"}, timeout=12.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200 and code in resp.text:
                    return True, "Code found on Facebook Page."
        except Exception as e:
            logger.debug(f"Facebook challenge check error: {e}")
        return False, f"Code '{code}' not detected on Facebook Page."


verification_service = OwnershipVerificationService()

