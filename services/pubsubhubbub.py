import httpx
from typing import Tuple
from core.config import settings
from core.logger import logger


class PubSubHubbubClient:
    """
    Manages WebSub / PubSubHubbub subscription requests to YouTube's hub.
    Hub URL: https://pubsubhubbub.appspot.com/subscribe
    Topic URL: https://www.youtube.com/xml/feeds/videos.xml?channel_id={channel_id}
    """

    def __init__(self, hub_url: str = settings.PUBSUBHUBBUB_HUB_URL):
        self.hub_url = hub_url
        self.callback_url = f"{settings.BASE_WEBHOOK_URL.rstrip('/')}/webhooks/youtube"
        self.secret = settings.PUBSUBHUBBUB_SECRET

    def get_topic_url(self, channel_id: str) -> str:
        return f"https://www.youtube.com/xml/feeds/videos.xml?channel_id={channel_id}"

    async def subscribe(self, channel_id: str, lease_seconds: int = 864000) -> Tuple[bool, str]:
        """
        Sends an asynchronous subscription request to Google's PubSubHubbub hub.
        The hub will issue a GET challenge to callback_url before confirming.
        """
        topic_url = self.get_topic_url(channel_id)
        payload = {
            "hub.callback": self.callback_url,
            "hub.mode": "subscribe",
            "hub.topic": topic_url,
            "hub.verify": "async",
            "hub.secret": self.secret,
            "hub.lease_seconds": str(lease_seconds),
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    self.hub_url,
                    data=payload,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                if response.status_code in (202, 204):
                    logger.info(f"PubSubHubbub subscription accepted (status {response.status_code}) for channel: {channel_id}")
                    return True, "Subscription request accepted by hub."
                else:
                    logger.warning(
                        f"PubSubHubbub subscription returned status {response.status_code}: {response.text}"
                    )
                    return False, f"Hub returned {response.status_code}: {response.text}"
        except Exception as e:
            logger.error(f"Failed to communicate with PubSubHubbub hub: {e}")
            return False, str(e)

    async def unsubscribe(self, channel_id: str) -> Tuple[bool, str]:
        """Sends an unsubscription request to the hub."""
        topic_url = self.get_topic_url(channel_id)
        payload = {
            "hub.callback": self.callback_url,
            "hub.mode": "unsubscribe",
            "hub.topic": topic_url,
            "hub.verify": "async",
            "hub.secret": self.secret,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    self.hub_url,
                    data=payload,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                if response.status_code in (202, 204):
                    logger.info(f"PubSubHubbub unsubscribe accepted for channel {channel_id}")
                    return True, "Unsubscribed successfully."
                return False, f"Hub status {response.status_code}: {response.text}"
        except Exception as e:
            logger.error(f"Failed to unsubscribe from PubSubHubbub: {e}")
            return False, str(e)


pubsub_client = PubSubHubbubClient()

