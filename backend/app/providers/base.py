from dataclasses import dataclass, field
from datetime import datetime


class ProviderError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class MediaGone(ProviderError):
    """Post deleted or made private (TR-4)."""


class TokenInvalid(ProviderError):
    """invalid_grant / expired token: account needs re-auth."""


@dataclass
class TokenSet:
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None
    scopes: list[str] = field(default_factory=list)


@dataclass
class Profile:
    external_id: str
    handle: str
    account_type: str  # BUSINESS | MEDIA_CREATOR | PERSONAL | CHANNEL
    followers: int
    media_count: int
    followers_30d_ago: int | None = None


@dataclass
class Media:
    id: str
    caption: str
    media_type: str
    media_product_type: str
    permalink: str
    thumbnail_url: str | None
    timestamp: datetime
    duration_s: int | None
    owner_external_id: str


@dataclass
class Insights:
    views: int
    reach: int
    likes: int
    comments: int
    saves: int
    shares: int
    raw: dict = field(default_factory=dict)

    @property
    def engagement(self) -> int:
        return self.likes + self.comments + self.saves + self.shares


class SocialProvider:
    platform: str
    scopes: list[str]

    def authorize_url(self, state: str, redirect_uri: str) -> str: ...
    def exchange_code(self, code: str, redirect_uri: str) -> TokenSet: ...
    def refresh(self, token: TokenSet) -> TokenSet: ...
    def profile(self, access_token: str) -> Profile: ...
    def list_media(self, access_token: str, limit: int = 30) -> list[Media]: ...
    def insights(self, access_token: str, media_id: str) -> Insights: ...
    def online_followers(self, access_token: str) -> dict[int, int] | None: ...
    def comment_sample(self, access_token: str, media_id: str) -> list[str]: ...
