import re
from datetime import datetime
from typing import Optional, List
import httpx

from core.config import settings
from core.logger import logger
from models.monitored_source import PlatformType
from services.base import SocialMonitor, PostPayload, SourceValidationResult


class FacebookMonitor(SocialMonitor):
    """
    Compliant Facebook Monitor.
    Integration Strategy:
    1. Managed Pages: Real-time Meta Webhooks for 'feed' field.
    2. Public Pages: Periodic Graph API polling with a valid Meta access token.
    3. Complies with Meta Platform Terms: No unauthorized scraping or automated user account simulation.
    """

    @property
    def platform(self) -> PlatformType:
        return PlatformType.FACEBOOK

    def _clean_handle(self, handle_or_url: str) -> str:
        cleaned = handle_or_url.strip()
        if "facebook.com/" in cleaned:
            match = re.search(r"facebook\.com/([a-zA-Z0-9_.-]+)", cleaned)
            if match:
                return match.group(1)
        return cleaned.lstrip("@").strip()

    async def validate_source(self, handle_or_url: str) -> SourceValidationResult:
        page_identifier = self._clean_handle(handle_or_url)
        if not page_identifier:
            return SourceValidationResult(
                is_valid=False,
                source_id="",
                normalized_handle=handle_or_url,
                display_name="",
                profile_url="",
                error_message="Invalid Facebook Page identifier.",
            )

        if settings.FACEBOOK_ACCESS_TOKEN:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    url = f"https://graph.facebook.com/{settings.META_GRAPH_API_VERSION}/{page_identifier}"
                    params = {
                        "fields": "id,name,link,fan_count,about",
                        "access_token": settings.FACEBOOK_ACCESS_TOKEN,
                    }
                    resp = await client.get(url, params=params)
                    if resp.status_code == 200:
                        data = resp.json()
                        page_id = data.get("id")
                        name = data.get("name", page_identifier)
                        link = data.get("link", f"https://www.facebook.com/{page_identifier}")
                        return SourceValidationResult(
                            is_valid=True,
                            source_id=page_id,
                            normalized_handle=f"@{page_identifier}",
                            display_name=name,
                            profile_url=link,
                            metadata={
                                "fan_count": data.get("fan_count", 0),
                                "about": data.get("about", ""),
                            },
                        )
            except Exception as e:
                logger.error(f"Facebook Graph API lookup error: {e}")

        # Basic fallback validation
        if re.match(r"^[a-zA-Z0-9_.-]{2,50}$", page_identifier):
            return SourceValidationResult(
                is_valid=True,
                source_id=page_identifier,
                normalized_handle=f"@{page_identifier}",
                display_name=page_identifier,
                profile_url=f"https://www.facebook.com/{page_identifier}",
                metadata={"note": "Registered using handle verification (API polling mode)."},
            )

        return SourceValidationResult(
            is_valid=False,
            source_id="",
            normalized_handle=f"@{page_identifier}",
            display_name="",
            profile_url="",
            error_message="Facebook Page not found or invalid.",
        )

    async def fetch_latest_posts(
        self,
        source_id: str,
        last_seen_post_id: Optional[str] = None,
        limit: int = 5,
    ) -> List[PostPayload]:
        posts: List[PostPayload] = []

        if settings.FACEBOOK_ACCESS_TOKEN:
            try:
                async with httpx.AsyncClient(timeout=12.0) as client:
                    url = f"https://graph.facebook.com/{settings.META_GRAPH_API_VERSION}/{source_id}/posts"
                    params = {
                        "fields": "id,message,created_time,permalink_url,full_picture",
                        "limit": limit,
                        "access_token": settings.FACEBOOK_ACCESS_TOKEN,
                    }
                    resp = await client.get(url, params=params)
                    if resp.status_code == 200:
                        data = resp.json()
                        items = data.get("data", [])
                        for item in items:
                            pid = item.get("id")
                            if not pid:
                                continue
                            if last_seen_post_id and pid == last_seen_post_id:
                                break

                            created_time_str = item.get("created_time")
                            posted_at = None
                            if created_time_str:
                                try:
                                    posted_at = datetime.fromisoformat(created_time_str.replace("Z", "+00:00"))
                                except Exception:
                                    pass

                            message = item.get("message", "New Facebook Post")
                            post = PostPayload(
                                platform=PlatformType.FACEBOOK,
                                creator_handle=f"@{source_id}",
                                creator_name=source_id,
                                post_id=pid,
                                post_url=item.get("permalink_url", f"https://facebook.com/{pid}"),
                                caption=message,
                                media_type="photo" if item.get("full_picture") else "text",
                                preview_image_url=item.get("full_picture"),
                                posted_at=posted_at,
                            )
                            posts.append(post)
                        return posts
            except Exception as e:
                logger.error(f"Error fetching Facebook posts for {source_id}: {e}")

        return posts


facebook_monitor = FacebookMonitor()

