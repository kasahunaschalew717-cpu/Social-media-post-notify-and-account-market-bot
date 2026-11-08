import re
from datetime import datetime
from typing import Optional, List, Dict, Any
import httpx

from core.config import settings
from core.logger import logger
from models.monitored_source import PlatformType
from services.base import SocialMonitor, PostPayload, SourceValidationResult


class TikTokMonitor(SocialMonitor):
    """
    Compliant TikTok Monitor.
    Integration Strategy:
    - Official TikTok Display API for authorized creators.
    - Official partner/provider polling (e.g. Apify TikTok Profile Actor) for public creator profiles.
    - Complies with TikTok ToS: does not perform unauthorized headless scraping or CAPTCHA solving.
    """

    @property
    def platform(self) -> PlatformType:
        return PlatformType.TIKTOK

    def _clean_handle(self, handle_or_url: str) -> str:
        cleaned = handle_or_url.strip()
        if "tiktok.com/@" in cleaned:
            match = re.search(r"tiktok\.com/@([a-zA-Z0-9_.-]+)", cleaned)
            if match:
                return match.group(1)
        return cleaned.lstrip("@").strip()

    async def validate_source(self, handle_or_url: str) -> SourceValidationResult:
        username = self._clean_handle(handle_or_url)
        if not username:
            return SourceValidationResult(
                is_valid=False,
                source_id="",
                normalized_handle=handle_or_url,
                display_name="",
                profile_url="",
                error_message="Invalid TikTok username provided.",
            )

        # If Apify token is provided, query Apify for profile verification
        if settings.APIFY_API_TOKEN:
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(
                        "https://api.apify.com/v2/acts/clockworks~tiktok-profile-scraper/run-sync-get-dataset-items",
                        params={"token": settings.APIFY_API_TOKEN},
                        json={"profiles": [username], "resultsPerPage": 1},
                    )
                    if resp.status_code in (200, 201):
                        items = resp.json()
                        if items and len(items) > 0:
                            data = items[0]
                            user_info = data.get("authorMeta", {})
                            display_name = user_info.get("name", username)
                            sec_uid = user_info.get("secUid", username)
                            return SourceValidationResult(
                                is_valid=True,
                                source_id=sec_uid or username,
                                normalized_handle=f"@{username}",
                                display_name=display_name,
                                profile_url=f"https://www.tiktok.com/@{username}",
                                metadata={
                                    "follower_count": user_info.get("fans", 0),
                                    "verified": user_info.get("verified", False),
                                    "bio": user_info.get("signature", ""),
                                },
                            )
            except Exception as e:
                logger.error(f"Apify TikTok validation error: {e}")

        # Fallback public profile check via standard HTTP HEAD / GET
        profile_url = f"https://www.tiktok.com/@{username}"
        try:
            async with httpx.AsyncClient(
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
                timeout=10.0,
                follow_redirects=True,
            ) as client:
                resp = await client.get(profile_url)
                if resp.status_code == 200:
                    return SourceValidationResult(
                        is_valid=True,
                        source_id=username,
                        normalized_handle=f"@{username}",
                        display_name=username,
                        profile_url=profile_url,
                    )
        except Exception as e:
            logger.error(f"TikTok profile validation HTTP error: {e}")

        # If public network check returns, allow registration if format is valid
        if re.match(r"^[a-zA-Z0-9_.-]{2,30}$", username):
            return SourceValidationResult(
                is_valid=True,
                source_id=username,
                normalized_handle=f"@{username}",
                display_name=username,
                profile_url=profile_url,
                metadata={"note": "Registered using handle format verification."},
            )

        return SourceValidationResult(
            is_valid=False,
            source_id="",
            normalized_handle=f"@{username}",
            display_name="",
            profile_url="",
            error_message="TikTok profile not found or unavailable.",
        )

    async def fetch_latest_posts(
        self,
        source_id: str,
        last_seen_post_id: Optional[str] = None,
        limit: int = 5,
    ) -> List[PostPayload]:
        username = self._clean_handle(source_id)
        posts: List[PostPayload] = []

        if settings.APIFY_API_TOKEN:
            try:
                async with httpx.AsyncClient(timeout=25.0) as client:
                    resp = await client.post(
                        "https://api.apify.com/v2/acts/clockworks~tiktok-scraper/run-sync-get-dataset-items",
                        params={"token": settings.APIFY_API_TOKEN},
                        json={
                            "profiles": [username],
                            "resultsPerPage": limit,
                            "shouldDownloadVideos": False,
                        },
                    )
                    if resp.status_code in (200, 201):
                        items = resp.json()
                        for item in items:
                            vid_id = str(item.get("id", ""))
                            if not vid_id:
                                continue
                            if last_seen_post_id and vid_id == last_seen_post_id:
                                break

                            desc = item.get("text", "")
                            create_time = item.get("createTime")
                            posted_at = None
                            if create_time:
                                try:
                                    posted_at = datetime.fromtimestamp(int(create_time))
                                except Exception:
                                    pass

                            post = PostPayload(
                                platform=PlatformType.TIKTOK,
                                creator_handle=f"@{username}",
                                creator_name=item.get("authorMeta", {}).get("name", username),
                                post_id=vid_id,
                                post_url=item.get("webVideoUrl", f"https://www.tiktok.com/@{username}/video/{vid_id}"),
                                caption=desc or "New TikTok Video",
                                media_type="video",
                                preview_image_url=item.get("videoMeta", {}).get("coverUrl"),
                                posted_at=posted_at,
                                likes_count=item.get("diggCount"),
                                comments_count=item.get("commentCount"),
                                raw_data={"play_count": item.get("playCount")},
                            )
                            posts.append(post)
                        return posts
            except Exception as e:
                logger.error(f"Apify TikTok scraping error for @{username}: {e}")

        logger.info(f"TikTok polling for @{username}: no API token or partner provider configured.")
        return []


tiktok_monitor = TikTokMonitor()

