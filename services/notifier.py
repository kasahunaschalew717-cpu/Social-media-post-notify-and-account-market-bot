import asyncio
from datetime import datetime
from typing import List
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import RetryAfter, Forbidden, TelegramError

from core.config import settings
from core.logger import logger
from core.database import async_session_factory
from core.redis_client import redis_service
from models.monitored_source import MonitoredSource
from models.subscription import Subscription
from models.user import User
from models.notification_log import NotificationLog
from services.base import PostPayload
from sqlalchemy import select


class NotificationDispatcher:
    def __init__(self, bot_token: str = settings.TELEGRAM_BOT_TOKEN):
        self.bot = Bot(token=bot_token)

    def format_notification_text(self, post: PostPayload) -> str:
        """
        Formats the Telegram alert message according to the master prompt specifications.
        """
        platform_name = post.platform.value.capitalize()
        posted_str = post.posted_at.strftime("%Y-%m-%d %H:%M UTC") if post.posted_at else "Just now"

        caption_clean = post.caption.strip()
        if len(caption_clean) > 500:
            caption_clean = f"{caption_clean[:497]}..."

        lines = [
            f"🔔 <b>New post from {post.creator_handle} on {platform_name}!</b>\n",
            f"📝 <b>Title/Caption:</b>\n{caption_clean}\n",
        ]

        if post.preview_image_url and post.media_type != "video":
            lines.append(f"🖼️ <b>Media:</b> <a href=\"{post.preview_image_url}\">Photo Preview</a>")
        elif post.media_type == "video":
            lines.append(f"🎥 <b>Video:</b> <a href=\"{post.post_url}\">Watch Video</a>")

        lines.append(f"🔗 <b>Link:</b> <a href=\"{post.post_url}\">{post.post_url}</a>")
        lines.append(f"🕒 <b>Posted at:</b> {posted_str}")

        stats = []
        if post.likes_count is not None:
            stats.append(f"❤️ Likes: {post.likes_count:,}")
        if post.comments_count is not None:
            stats.append(f"💬 Comments: {post.comments_count:,}")
        if "views" in post.raw_data and post.raw_data["views"]:
            stats.append(f"👁️ Views: {post.raw_data['views']}")

        if stats:
            lines.append(" | ".join(stats))

        return "\n".join(lines)

    async def dispatch_post(self, source_id: int, post: PostPayload) -> int:
        """
        Sends the post alert to all active subscribers of the given source.
        Applies Redis deduplication, rate limit pacing, and logs the notification.
        Returns the number of successfully delivered messages.
        """
        # Step 1: Redis Deduplication
        is_dup = await redis_service.is_post_duplicate(post.platform.value, post.post_id)
        if is_dup:
            logger.info(f"Duplicate post ignored: {post.platform.value}:{post.post_id}")
            return 0

        # Step 2: Fetch active subscribers
        recipients: List[int] = []
        async with async_session_factory() as session:
            stmt = (
                select(User.telegram_id)
                .join(Subscription, Subscription.user_id == User.id)
                .where(
                    Subscription.source_id == source_id,
                    Subscription.is_active == True,
                    User.is_banned == False,
                )
            )
            result = await session.execute(stmt)
            recipients = [row[0] for row in result.fetchall()]

        if not recipients:
            logger.info(f"No subscribers for source {source_id} ({post.creator_handle})")
            return 0

        message_text = self.format_notification_text(post)
        delivered_count = 0

        for chat_id in recipients:
            try:
                # If preview image exists, send as photo with caption if <= 1024 chars,
                # otherwise send rich text message with disable_web_page_preview=False
                if post.preview_image_url and len(message_text) <= 1024:
                    try:
                        await self.bot.send_photo(
                            chat_id=chat_id,
                            photo=post.preview_image_url,
                            caption=message_text,
                            parse_mode=ParseMode.HTML,
                        )
                        delivered_count += 1
                    except Exception:
                        # Fallback to text message
                        await self.bot.send_message(
                            chat_id=chat_id,
                            text=message_text,
                            parse_mode=ParseMode.HTML,
                            disable_web_page_preview=False,
                        )
                        delivered_count += 1
                else:
                    await self.bot.send_message(
                        chat_id=chat_id,
                        text=message_text,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=False,
                    )
                    delivered_count += 1

                # Rate limiting pacing: 0.08s between sends to avoid Telegram limits
                await asyncio.sleep(0.08)

            except RetryAfter as e:
                logger.warning(f"Telegram FloodControl: retry after {e.retry_after}s")
                await asyncio.sleep(e.retry_after)
            except Forbidden:
                logger.info(f"User {chat_id} blocked the bot; skipping.")
            except TelegramError as e:
                logger.error(f"Telegram error delivering to {chat_id}: {e}")
            except Exception as e:
                logger.error(f"Unexpected error sending notification to {chat_id}: {e}")

        # Step 3: Log notification in database
        async with async_session_factory() as session:
            try:
                log_entry = NotificationLog(
                    source_id=source_id,
                    post_id=post.post_id,
                    post_title=post.caption[:250],
                    post_url=post.post_url,
                    recipients_count=delivered_count,
                    sent_at=datetime.utcnow(),
                )
                session.add(log_entry)

                # Update last_seen_post_id on source
                src_stmt = select(MonitoredSource).where(MonitoredSource.id == source_id)
                src_res = await session.execute(src_stmt)
                src_obj = src_res.scalar_one_or_none()
                if src_obj:
                    src_obj.last_seen_post_id = post.post_id
                    src_obj.last_polled_at = datetime.utcnow()

                await session.commit()
            except Exception as e:
                logger.error(f"Failed to record NotificationLog: {e}")

        logger.info(f"Successfully dispatched post {post.post_id} to {delivered_count} subscribers.")
        return delivered_count


notification_dispatcher = NotificationDispatcher()

