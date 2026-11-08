import re
from datetime import datetime
from typing import Optional, List, Dict, Any
import httpx

from core.config import settings
from core.logger import logger
from models.monitored_source import PlatformType
from services.base import SocialMonitor, PostPayload, SourceValidationResult


class InstagramMonitor(SocialMonitor):
    """
    Compliant Instagram Monitor.
    Integration Strategy:
    1. Authorized Accounts: Instagram Graph API Webhooks (media changes).
    2. Arbitrary Public Creators: Meta Graph API 'Business Discovery' endpoint
       (requires an authorized Instagram Business account token).
    3. Strict compliance: Does NOT scrape raw Instagram HTML or bypass Meta authentication.
    """

    @property
    def platform(self) -> PlatformType:
        return PlatformType.INSTAGRAM

    def _clean_handle(self, handle_or_url: str) -> str:
        cleaned = handle_or_url.strip()
        if "instagram.com/" in cleaned:
            match = re.search(r"instagram\.com/([a-zA-Z0-9_.-]+)", cleaned)
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
                error_message="Invalid Instagram username.",
            )

        # Use Business Discovery API if token is configured
        if settings.INSTAGRAM_ACCESS_TOKEN:
            try:
                # Query business discovery
                async with httpx.AsyncClient(timeout=12.0) as client:
                    # Note: We need a managed IG user ID or 'me' to call business_discovery
                    url = f"https://graph.facebook.com/{settings.META_GRAPH_API_VERSION}/me"
                    params = {
                        "fields": f"instagram_business_account{{business_discovery.username({username}){{id,username,name,biography,followers_count}}}}",
                        "access_token": settings.INSTAGRAM_ACCESS_TOKEN,
                    }
                    resp = await client.get(url, params=params)
                    if resp.status_code == 200:
                        data = resp.json()
                        ig_acc = data.get("instagram_business_account", {})
                        discovery = ig_acc.get("business_discovery", {})
                        if discovery:
                            return SourceValidationResult(
                                is_valid=True,
                                source_id=discovery.get("id", username),
                                normalized_handle=f"@{discovery.get('username', username)}",
                                display_name=discovery.get("name", username),
                                profile_url=f"https://www.instagram.com/{username}/",
                                metadata={
                                    "followers_count": discovery.get("followers_count", 0),
                                    "biography": discovery.get("biography", ""),
                                },
                            )
            except Exception as e:
                logger.error(f"Instagram Business Discovery validation error: {e}")

        # Basic format validation fallback
        if re.match(r"^[a-zA-Z0-9_.-]{1,30}$", username):
            return SourceValidationResult(
                is_valid=True,
                source_id=username,
                normalized_handle=f"@{username}",
                display_name=username,
                profile_url=f"https://www.instagram.com/{username}/",
                metadata={"note": "Registered using handle verification (API polling enabled)."},
            )

        return SourceValidationResult(
            is_valid=False,
            source_id="",
            normalized_handle=f"@{username}",
            display_name="",
            profile_url="",
            error_message="Instagram account not found or invalid handle.",
        )

    async def fetch_latest_posts(
        self,
        source_id: str,
        last_seen_post_id: Optional[str] = None,
        limit: int = 5,
    ) -> List[PostPayload]:
        username = self._clean_handle(source_id)
        posts: List[PostPayload] = []

        if settings.INSTAGRAM_ACCESS_TOKEN:
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    url = f"https://graph.facebook.com/{settings.META_GRAPH_API_VERSION}/me"
                    fields = (
                        f"instagram_business_account{{business_discovery.username({username})"
                        f"{{media{{id,caption,media_type,media_url,permalink,timestamp,like_count,comments_count}}}}}}"
                    )
                    params = {
                        "fields": fields,
                        "access_token": settings.INSTAGRAM_ACCESS_TOKEN,
                    }
                    resp = await client.get(url, params=params)
                    if resp.status_code == 200:
                        data = resp.json()
                        media_items = (
                            data.get("instagram_business_account", {})
                            .get("business_discovery", {})
                            .get("media", {})
                            .get("data", [])
                        )

                        for item in media_items:
                            item_id = item.get("id")
                            if not item_id:
                                continue
                            if last_seen_post_id and item_id == last_seen_post_id:
                                break

                            timestamp_str = item.get("timestamp")
                            posted_at = None
                            if timestamp_str:
                                try:
                                    posted_at = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                                except Exception:
                                    pass

                            post = PostPayload(
                                platform=PlatformType.INSTAGRAM,
                                creator_handle=f"@{username}",
                                creator_name=username,
                                post_id=item_id,
                                post_url=item.get("permalink", f"https://www.instagram.com/p/{item_id}/"),
                                caption=item.get("caption", "New Instagram Post"),
                                media_type=item.get("media_type", "IMAGE").lower(),
                                preview_image_url=item.get("media_url"),
                                posted_at=posted_at,
                                likes_count=item.get("like_count"),
                                comments_count=item.get("comments_count"),
                            )
                            posts.append(post)
                            if len(posts) >= limit:
                                break
                        return posts
            except Exception as e:
                logger.error(f"Error querying Instagram Business Discovery for @{username}: {e}")

        return posts


instagram_monitor = InstagramMonitor()

