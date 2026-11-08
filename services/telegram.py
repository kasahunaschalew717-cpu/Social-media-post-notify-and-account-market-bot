import re
from datetime import datetime
from typing import Optional, List
import httpx
from bs4 import BeautifulSoup

from core.config import settings
from core.logger import logger
from models.monitored_source import PlatformType
from services.base import SocialMonitor, PostPayload, SourceValidationResult


class TelegramMonitor(SocialMonitor):
    """
    Compliant Telegram public channel monitor using Telegram's official public
    web preview interface (https://t.me/s/{username}).
    Also supports Telethon client hooks if configured.
    """

    @property
    def platform(self) -> PlatformType:
        return PlatformType.TELEGRAM

    def _clean_handle(self, handle_or_url: str) -> str:
        cleaned = handle_or_url.strip()
        if "t.me/" in cleaned:
            # Handle forms like https://t.me/durov or t.me/s/durov
            cleaned = re.sub(r"^https?://(www\.)?t\.me/(s/)?", "", cleaned)
            cleaned = cleaned.split("?")[0].split("/")[0]
        cleaned = cleaned.lstrip("@")
        return cleaned

    async def validate_source(self, handle_or_url: str) -> SourceValidationResult:
        username = self._clean_handle(handle_or_url)
        preview_url = f"https://t.me/s/{username}"

        try:
            async with httpx.AsyncClient(
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
                timeout=12.0,
                follow_redirects=True,
            ) as client:
                resp = await client.get(preview_url)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    title_el = soup.find("div", class_="tgme_channel_info_title")
                    desc_el = soup.find("div", class_="tgme_channel_info_description")
                    counter_el = soup.find("div", class_="tgme_channel_info_counter")

                    if title_el:
                        display_name = title_el.get_text(strip=True)
                        desc = desc_el.get_text(strip=True) if desc_el else ""
                        subscribers = counter_el.get_text(strip=True) if counter_el else ""

                        return SourceValidationResult(
                            is_valid=True,
                            source_id=username.lower(),
                            normalized_handle=f"@{username}",
                            display_name=display_name,
                            profile_url=f"https://t.me/{username}",
                            metadata={
                                "description": desc,
                                "subscribers": subscribers,
                            },
                        )
        except Exception as e:
            logger.error(f"Error validating Telegram channel @{username}: {e}")

        return SourceValidationResult(
            is_valid=False,
            source_id="",
            normalized_handle=f"@{username}",
            display_name="",
            profile_url="",
            error_message=f"Could not find public Telegram channel @{username}. Ensure it is public.",
        )

    async def fetch_latest_posts(
        self,
        source_id: str,
        last_seen_post_id: Optional[str] = None,
        limit: int = 5,
    ) -> List[PostPayload]:
        username = self._clean_handle(source_id)
        url = f"https://t.me/s/{username}"
        posts: List[PostPayload] = []

        try:
            async with httpx.AsyncClient(
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
                timeout=12.0,
                follow_redirects=True,
            ) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    logger.warning(f"Failed to fetch Telegram preview for @{username}, status: {resp.status_code}")
                    return []

                soup = BeautifulSoup(resp.text, "html.parser")
                message_divs = soup.find_all("div", class_="tgme_widget_message")

                for msg_div in reversed(message_divs):
                    post_data_id = msg_div.get("data-post")  # e.g. "durov/214"
                    if not post_data_id:
                        continue

                    raw_id = post_data_id.split("/")[-1]
                    if last_seen_post_id and raw_id == last_seen_post_id:
                        break

                    text_div = msg_div.find("div", class_="tgme_widget_message_text")
                    caption = text_div.get_text("\n", strip=True) if text_div else ""

                    # Find photos / media
                    photo_wraps = msg_div.find_all("a", class_="tgme_widget_message_photo_wrap")
                    preview_image_url = None
                    media_type = "text"
                    if photo_wraps:
                        media_type = "photo"
                        style = photo_wraps[0].get("style", "")
                        match = re.search(r"url\('([^']+)'\)", style)
                        if match:
                            preview_image_url = match.group(1)

                    video_wrap = msg_div.find("video", class_="tgme_widget_message_video")
                    if video_wrap:
                        media_type = "video"

                    time_el = msg_div.find("time", class_="time")
                    posted_at = None
                    if time_el and time_el.get("datetime"):
                        try:
                            posted_at = datetime.fromisoformat(time_el["datetime"])
                        except Exception:
                            pass

                    views_el = msg_div.find("span", class_="tgme_widget_message_views")
                    views_count = views_el.get_text(strip=True) if views_el else None

                    post = PostPayload(
                        platform=PlatformType.TELEGRAM,
                        creator_handle=f"@{username}",
                        creator_name=username,
                        post_id=raw_id,
                        post_url=f"https://t.me/{post_data_id}",
                        caption=caption or "Shared a photo or media update.",
                        media_type=media_type,
                        preview_image_url=preview_image_url,
                        posted_at=posted_at,
                        likes_count=None,
                        comments_count=None,
                        raw_data={"views": views_count, "data_post": post_data_id},
                    )
                    posts.append(post)

                    if len(posts) >= limit:
                        break

        except Exception as e:
            logger.error(f"Error scraping Telegram public channel preview @{username}: {e}")

        return posts


telegram_monitor = TelegramMonitor()

