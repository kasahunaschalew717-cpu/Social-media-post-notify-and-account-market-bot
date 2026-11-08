from fastapi import APIRouter, Request, Response, Header, HTTPException, Query, status
from typing import Optional
from core.config import settings
from core.logger import logger
from core.security import verify_hmac_sha1_signature
from core.database import async_session_factory
from models.processed_event import ProcessedEvent
from models.monitored_source import MonitoredSource, PlatformType
from services.youtube import youtube_monitor
from services.notifier import notification_dispatcher
from sqlalchemy import select

router = APIRouter(prefix="/webhooks/youtube", tags=["YouTube Webhooks"])


@router.get("", status_code=status.HTTP_200_OK)
async def youtube_pubsub_challenge(
    request: Request,
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_topic: Optional[str] = Query(None, alias="hub.topic"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
    hub_lease_seconds: Optional[int] = Query(None, alias="hub.lease_seconds"),
):
    """
    Handles Google PubSubHubbub subscription verification handshake.
    When subscribing, Google sends a GET request with hub.challenge.
    We must echo back hub.challenge with HTTP 200 to confirm the subscription.
    """
    logger.info(f"Received PubSubHubbub verification request: mode={hub_mode}, topic={hub_topic}")

    if hub_mode in ("subscribe", "unsubscribe") and hub_challenge:
        logger.info(f"PubSubHubbub subscription handshake confirmed for topic: {hub_topic}")
        return Response(content=hub_challenge, media_type="text/plain")

    raise HTTPException(status_code=400, detail="Invalid verification request parameters.")


@router.post("", status_code=status.HTTP_200_OK)
async def youtube_pubsub_callback(
    request: Request,
    x_hub_signature: Optional[str] = Header(None, alias="X-Hub-Signature"),
):
    """
    Receives incoming WebSub push notifications from YouTube when a video is published.
    Validates HMAC-SHA1 signature and processes new post alerts.
    """
    raw_body = await request.body()

    # Step 1: Signature Verification (HMAC-SHA1)
    if settings.PUBSUBHUBBUB_SECRET:
        if not x_hub_signature:
            logger.warning("YouTube webhook missing X-Hub-Signature header.")
            raise HTTPException(status_code=403, detail="Missing signature header.")

        is_valid = verify_hmac_sha1_signature(raw_body, x_hub_signature, settings.PUBSUBHUBBUB_SECRET)
        if not is_valid:
            logger.warning("YouTube webhook signature verification failed!")
            raise HTTPException(status_code=403, detail="Invalid HMAC signature.")

    # Step 2: Parse Atom XML
    posts = youtube_monitor.parse_atom_feed(raw_body)
    if not posts:
        logger.info("Received empty or unparseable YouTube feed push.")
        return Response(content="OK", media_type="text/plain")

    for post in posts:
        # Step 3: Webhook Idempotency Check
        event_key = f"yt_push_{post.post_id}"
        async with async_session_factory() as session:
            stmt = select(ProcessedEvent).where(ProcessedEvent.event_id == event_key)
            existing = await session.execute(stmt)
            if existing.scalar_one_or_none():
                logger.info(f"YouTube event {event_key} already processed; skipping.")
                continue

            # Record event as processed
            session.add(ProcessedEvent(event_id=event_key, source="youtube_websub"))
            await session.commit()

        # Step 4: Find MonitoredSource corresponding to channel
        channel_id = post.raw_data.get("channel_id")
        async with async_session_factory() as session:
            # Query source by source_id or handle
            src_stmt = select(MonitoredSource).where(
                MonitoredSource.platform == PlatformType.YOUTUBE,
                MonitoredSource.is_active == True,
            )
            res = await session.execute(src_stmt)
            sources = res.scalars().all()

            matched_source = None
            for src in sources:
                if channel_id and src.source_id == channel_id:
                    matched_source = src
                    break
                elif src.handle.lower() == post.creator_handle.lower():
                    matched_source = src
                    break

            if matched_source:
                logger.info(f"Matched YouTube post to source #{matched_source.id} ({matched_source.handle})")
                await notification_dispatcher.dispatch_post(matched_source.id, post)
            else:
                logger.warning(f"No active MonitoredSource matched for YouTube post {post.post_id}")

    return Response(content="OK", media_type="text/plain")

