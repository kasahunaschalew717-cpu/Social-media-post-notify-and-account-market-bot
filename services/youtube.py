import re
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Optional, List
import httpx

from core.config import settings
from core.logger import logger
from models.monitored_source import PlatformType
from services.base import SocialMonitor, PostPayload, SourceValidationResult
from services.pubsubhubbub import pubsub_client

# XML Namespaces used in YouTube Atom feeds
ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}


class YouTubeMonitor(SocialMonitor):
    @property
    def platform(self) -> PlatformType:
        return PlatformType.YOUTUBE

    async def validate_source(self, handle_or_url: str) -> SourceValidationResult:
        """
        Validates YouTube source by handle (@username), channel ID (UC...), or URL.
        Resolves to a canonical Channel ID (UC...).
        """
        cleaned = handle_or_url.strip()
        channel_id = None
        handle = None

        # Check if handle_or_url is a direct channel ID
        if re.match(r"^UC[a-zA-Z0-9_-]{22}$", cleaned):
            channel_id = cleaned
            handle = cleaned
        elif "youtube.com/channel/" in cleaned:
            match = re.search(r"youtube\.com/channel/(UC[a-zA-Z0-9_-]{22})", cleaned)
            if match:
                channel_id = match.group(1)
                handle = channel_id
        elif "@" in cleaned:
            # Handle format: @mkbhd or https://youtube.com/@mkbhd
            match = re.search(r"@([a-zA-Z0-9_.-]+)", cleaned)
            if match:
                handle = f"@{match.group(1)}"

        # If API key is available, use official YouTube Data API v3
        if settings.YOUTUBE_API_KEY:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    if channel_id:
                        params = {
                            "part": "snippet,statistics",
                            "id": channel_id,
                            "key": settings.YOUTUBE_API_KEY,
                        }
                    elif handle:
                        clean_handle = handle.lstrip("@")
                        params = {
                            "part": "snippet,statistics",
                            "forHandle": clean_handle,
                            "key": settings.YOUTUBE_API_KEY,
                        }
                    else:
                        params = {
                            "part": "snippet",
                            "q": cleaned,
                            "type": "channel",
                            "key": settings.YOUTUBE_API_KEY,
                        }

                    resp = await client.get(
                        "https://www.googleapis.com/youtube/v3/channels",
                        params=params,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        items = data.get("items", [])
                        if items:
                            item = items[0]
                            cid = item["id"]
                            snippet = item["snippet"]
                            custom_url = snippet.get("customUrl", f"@{snippet.get('title')}")
                            return SourceValidationResult(
                                is_valid=True,
                                source_id=cid,
                                normalized_handle=custom_url if custom_url.startswith("@") else f"@{custom_url}",
                                display_name=snippet.get("title", ""),
                                profile_url=f"https://www.youtube.com/channel/{cid}",
                                metadata={
                                    "description": snippet.get("description", ""),
                                    "subscriber_count": item.get("statistics", {}).get("subscriberCount", 0),
                                    "video_count": item.get("statistics", {}).get("videoCount", 0),
                                },
                            )
            except Exception as e:
                logger.error(f"YouTube Data API error: {e}")

        # Fallback without API key: fetch channel RSS / HTML
        if channel_id:
            rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(rss_url)
                    if resp.status_code == 200 and "<title>" in resp.text:
                        root = ET.fromstring(resp.content)
                        title_el = root.find("atom:title", ATOM_NS)
                        title = title_el.text if title_el is not None else channel_id
                        return SourceValidationResult(
                            is_valid=True,
                            source_id=channel_id,
                            normalized_handle=f"@{channel_id}",
                            display_name=title,
                            profile_url=f"https://www.youtube.com/channel/{channel_id}",
                        )
            except Exception as e:
                logger.error(f"YouTube RSS validation error: {e}")

        # If only handle without API key, attempt web scrape of canonical channel_id
        if handle:
            clean_handle = handle.lstrip("@")
            try:
                async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0"}, timeout=10.0) as client:
                    resp = await client.get(f"https://www.youtube.com/@{clean_handle}")
                    if resp.status_code == 200:
                        match = re.search(r"\"channelId\":\"(UC[a-zA-Z0-9_-]{22})\"", resp.text)
                        if match:
                            cid = match.group(1)
                            return SourceValidationResult(
                                is_valid=True,
                                source_id=cid,
                                normalized_handle=f"@{clean_handle}",
                                display_name=clean_handle,
                                profile_url=f"https://www.youtube.com/channel/{cid}",
                            )
            except Exception as e:
                logger.error(f"YouTube handle scraping fallback failed: {e}")

        return SourceValidationResult(
            is_valid=False,
            source_id="",
            normalized_handle=cleaned,
            display_name="",
            profile_url="",
            error_message="Could not locate YouTube channel. Please verify the handle or channel URL.",
        )

    async def register_hub_subscription(self, channel_id: str) -> bool:
        """Subscribes to YouTube PubSubHubbub push notifications for this channel."""
        success, msg = await pubsub_client.subscribe(channel_id)
        if not success:
            logger.warning(f"PubSubHubbub registration failed for channel {channel_id}: {msg}")
        return success

    def parse_atom_feed(self, xml_content: str | bytes) -> List[PostPayload]:
        """
        Parses incoming XML Atom feed pushed by YouTube via PubSubHubbub or fetched from RSS.
        """
        posts: List[PostPayload] = []
        try:
            root = ET.fromstring(xml_content)
            entries = root.findall("atom:entry", ATOM_NS)

            for entry in entries:
                video_id_el = entry.find("yt:videoId", ATOM_NS)
                if video_id_el is None or not video_id_el.text:
                    continue
                video_id = video_id_el.text

                title_el = entry.find("atom:title", ATOM_NS)
                title = title_el.text if title_el is not None and title_el.text else "New Video"

                author_name = "YouTube Creator"
                author_el = entry.find("atom:author/atom:name", ATOM_NS)
                if author_el is not None and author_el.text:
                    author_name = author_el.text

                published_el = entry.find("atom:published", ATOM_NS)
                posted_at = None
                if published_el is not None and published_el.text:
                    try:
                        posted_at = datetime.fromisoformat(published_el.text.replace("Z", "+00:00"))
                    except Exception:
                        pass

                # Media group description & thumbnail
                caption = title
                media_group = entry.find("media:group", ATOM_NS)
                preview_image_url = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
                if media_group is not None:
                    desc_el = media_group.find("media:description", ATOM_NS)
                    if desc_el is not None and desc_el.text:
                        # Shorten caption preview if very long
                        raw_desc = desc_el.text.strip()
                        if raw_desc:
                            caption = f"{title}\n\n{raw_desc[:300]}..."

                    thumb_el = media_group.find("media:thumbnail", ATOM_NS)
                    if thumb_el is not None and "url" in thumb_el.attrib:
                        preview_image_url = thumb_el.attrib["url"]

                post = PostPayload(
                    platform=PlatformType.YOUTUBE,
                    creator_handle=f"@{author_name}",
                    creator_name=author_name,
                    post_id=video_id,
                    post_url=f"https://www.youtube.com/watch?v={video_id}",
                    caption=caption,
                    media_type="video",
                    media_urls=[f"https://www.youtube.com/watch?v={video_id}"],
                    preview_image_url=preview_image_url,
                    posted_at=posted_at,
                    raw_data={"video_id": video_id, "title": title},
                )
                posts.append(post)

        except Exception as e:
            logger.error(f"Failed to parse YouTube Atom XML feed: {e}")

        return posts

    async def fetch_latest_posts(
        self,
        source_id: str,
        last_seen_post_id: Optional[str] = None,
        limit: int = 5,
    ) -> List[PostPayload]:
        """
        Fallback RSS polling for YouTube in case WebSub is delayed or not yet active.
        """
        rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={source_id}"
        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                resp = await client.get(rss_url)
                if resp.status_code == 200:
                    posts = self.parse_atom_feed(resp.content)
                    if last_seen_post_id:
                        # Return only posts newer than last_seen_post_id
                        new_posts = []
                        for p in posts:
                            if p.post_id == last_seen_post_id:
                                break
                            new_posts.append(p)
                        return new_posts[:limit]
                    return posts[:limit]
        except Exception as e:
            logger.error(f"Error fetching YouTube RSS for channel {source_id}: {e}")
        return []


youtube_monitor = YouTubeMonitor()

