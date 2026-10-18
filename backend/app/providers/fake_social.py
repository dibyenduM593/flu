"""Simulated Instagram API (Instagram Login) and YouTube Data/Analytics API.

Response shapes mirror the real endpoints documented in the PRD so services are written against
the same contract the live adapters satisfy.
"""
import math
import secrets
from datetime import timedelta
from urllib.parse import urlencode

import jwt
from sqlalchemy.orm import Session

from ..clock import now
from ..config import settings
from ..models import FakeAccount, FakeMedia
from .base import Insights, Media, MediaGone, Profile, ProviderError, SocialProvider, TokenInvalid, TokenSet
from .fake_world import follower_history, metrics_at, rng_for


class _FakeBase(SocialProvider):
    platform = ""
    scopes: list[str] = []

    def __init__(self, db: Session):
        self.db = db

    # ---- OAuth: the consent screen is a page in the web app (/dev/connect)
    def authorize_url(self, state: str, redirect_uri: str) -> str:
        q = urlencode({"platform": self.platform, "state": state, "redirect_uri": redirect_uri,
                       "scope": ",".join(self.scopes)})
        return f"{settings.web_origin}/dev/connect?{q}"

    @staticmethod
    def issue_code(external_id: str) -> str:
        return jwt.encode({"ext": external_id, "exp": int((now() + timedelta(minutes=10)).timestamp())},
                          settings.jwt_secret, algorithm="HS256")

    def exchange_code(self, code: str, redirect_uri: str) -> TokenSet:
        try:
            data = jwt.decode(code, settings.jwt_secret, algorithms=["HS256"], options={"verify_exp": False})
        except jwt.InvalidTokenError:
            raise ProviderError("invalid_code", "authorization code is invalid")
        tok = f"fake_{self.platform}.{data['ext']}.{secrets.token_hex(8)}"
        ttl = timedelta(days=60) if self.platform == "instagram" else timedelta(hours=1)
        return TokenSet(access_token=tok, refresh_token=f"fake_refresh.{data['ext']}.{secrets.token_hex(8)}",
                        expires_at=now() + ttl, scopes=list(self.scopes))

    def refresh(self, token: TokenSet) -> TokenSet:
        ext = (token.refresh_token or token.access_token).split(".")[1]
        acc = self.db.get(FakeAccount, ext)
        if not acc or acc.persona.get("revoked"):
            raise TokenInvalid("invalid_grant", "refresh token revoked")
        ttl = timedelta(days=60) if self.platform == "instagram" else timedelta(hours=1)
        return TokenSet(access_token=f"fake_{self.platform}.{ext}.{secrets.token_hex(8)}",
                        refresh_token=token.refresh_token, expires_at=now() + ttl, scopes=token.scopes)

    def _account(self, access_token: str) -> FakeAccount:
        try:
            ext = access_token.split(".")[1]
        except (AttributeError, IndexError):
            raise TokenInvalid("invalid_token", "malformed token")
        acc = self.db.get(FakeAccount, ext)
        if not acc or acc.persona.get("revoked"):
            raise TokenInvalid("invalid_token", "token revoked")
        return acc

    def profile(self, access_token: str) -> Profile:
        acc = self._account(access_token)
        n = self.db.query(FakeMedia).filter_by(account_external_id=acc.external_id, deleted=False).count()
        return Profile(external_id=acc.external_id, handle=acc.handle, account_type=acc.account_type,
                       followers=acc.followers, media_count=n, followers_30d_ago=follower_history(acc))

    def list_media(self, access_token: str, limit: int = 30) -> list[Media]:
        acc = self._account(access_token)
        rows = (self.db.query(FakeMedia).filter_by(account_external_id=acc.external_id, deleted=False)
                .filter(FakeMedia.posted_at <= now()).order_by(FakeMedia.posted_at.desc()).limit(limit).all())
        return [Media(id=m.id, caption=m.caption, media_type=m.media_type, media_product_type=m.media_product_type,
                      permalink=m.permalink, thumbnail_url=None, timestamp=m.posted_at, duration_s=m.duration_s,
                      owner_external_id=acc.external_id) for m in rows]

    def find_media_by_permalink(self, access_token: str, permalink: str) -> Media | None:
        """Instagram has no lookup-by-URL: page through /me/media and match the permalink."""
        target = _norm(permalink)
        for m in self.list_media(access_token, limit=200):
            if _norm(m.permalink) == target:
                return m
        return None

    def insights(self, access_token: str, media_id: str) -> Insights:
        self._account(access_token)
        return self.public_insights(media_id)

    def public_insights(self, media_id: str) -> Insights:
        m = self.db.get(FakeMedia, media_id)
        if not m or m.deleted:
            raise MediaGone("media_gone", "media deleted or private")
        x = metrics_at(m, now())
        return Insights(views=x["views"], reach=x["reach"], likes=x["likes"], comments=x["comments"],
                        saves=x["saved"], shares=x["shares"], raw={"data": [{"name": k, "values": [{"value": v}]}
                                                                          for k, v in x.items()]})

    def online_followers(self, access_token: str) -> dict[int, int] | None:
        acc = self._account(access_token)
        if acc.followers < 100:
            return None  # Meta returns nothing under 100 followers
        r = rng_for("online:" + acc.handle)
        peaks = acc.persona["peak_hours"]
        out = {}
        for h in range(24):
            d = min(min(abs(h - p), 24 - abs(h - p)) for p in peaks)
            out[h] = int(acc.followers * 0.18 * math.exp(-d * d / 6) * r.uniform(0.85, 1.15)) + 3
        return out

    def comment_sample(self, access_token: str, media_id: str) -> list[str]:
        acc = self._account(access_token)
        r = rng_for("comments:" + media_id)
        if acc.persona.get("fraud") == "comment_bots":
            return ["Nice pic 🔥"] * 12 + ["Awesome 👍"] * 6 + ["love this", "where is this from?"]
        openers = ["where did you buy this", "trying this tomorrow", "this worked for me too", "price please",
                   "saved this", "my mom does this", "underrated creator", "which brand is this", "need part 2",
                   "so relatable", "can you do one for oily skin", "how long did it take"]
        tails = ["", " honestly", " for my sister", " in Pune", " before Diwali", " again", " pls reply",
                 " this week", " on a budget", " for college"]
        return [r.choice(openers) + r.choice(tails) for _ in range(20)]


def _norm(url: str) -> str:
    u = url.strip().split("?")[0].rstrip("/").lower()
    return u.replace("http://", "https://").replace("://instagram.com", "://www.instagram.com")


class FakeInstagram(_FakeBase):
    platform = "instagram"
    scopes = ["instagram_business_basic", "instagram_business_manage_insights"]


class FakeYouTube(_FakeBase):
    platform = "youtube"
    scopes = ["https://www.googleapis.com/auth/youtube.readonly",
              "https://www.googleapis.com/auth/yt-analytics.readonly"]

    def find_media_by_permalink(self, access_token: str, permalink: str) -> Media | None:
        # YouTube: videos.list by id, then snippet.channelId must equal the connected channel.
        acc = self._account(access_token)
        vid = permalink.rstrip("/").split("/")[-1].split("v=")[-1]
        m = self.db.query(FakeMedia).filter_by(shortcode=vid, deleted=False).first()
        if not m or m.account_external_id != acc.external_id:
            return None
        return Media(id=m.id, caption=m.caption, media_type=m.media_type, media_product_type=m.media_product_type,
                     permalink=m.permalink, thumbnail_url=None, timestamp=m.posted_at, duration_s=m.duration_s,
                     owner_external_id=acc.external_id)
