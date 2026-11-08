from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List
from models.monitored_source import PlatformType


@dataclass
class PostPayload:
    platform: PlatformType
    creator_handle: str
    creator_name: str
    post_id: str
    post_url: str
    caption: str
    media_type: str = "text"  # "text", "photo", "video", "album"
    media_urls: List[str] = field(default_factory=list)
    preview_image_url: Optional[str] = None
    posted_at: Optional[datetime] = None
    likes_count: Optional[int] = None
    comments_count: Optional[int] = None
    raw_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SourceValidationResult:
    is_valid: bool
    source_id: str
    normalized_handle: str
    display_name: str
    profile_url: str
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class SocialMonitor(ABC):
    """
    Abstract Base Class for all social platform monitors.
    Enforces a uniform interface for source lookup and post retrieval.
    """

    @property
    @abstractmethod
    def platform(self) -> PlatformType:
        """Returns the platform enum type."""
        pass

    @abstractmethod
    async def validate_source(self, handle_or_url: str) -> SourceValidationResult:
        """
        Validates that a creator account / channel exists and returns normalized metadata.
        """
        pass

    @abstractmethod
    async def fetch_latest_posts(
        self,
        source_id: str,
        last_seen_post_id: Optional[str] = None,
        limit: int = 5,
    ) -> List[PostPayload]:
        """
        Polls or retrieves the latest posts for a given source.
        Returns a list of PostPayload objects ordered chronologically (newest first).
        """
        pass

