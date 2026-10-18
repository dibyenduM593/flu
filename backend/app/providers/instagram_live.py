"""Instagram API with Instagram Login (graph.instagram.com).

Not exercised by the test suite: it needs a Meta app with Advanced Access on
instagram_business_manage_insights (App Review). Endpoint shapes follow the PRD; re-verify the
Graph version before going live."""
from datetime import timedelta
from urllib.parse import urlencode

import httpx

from ..clock import now
from ..config import settings
from .base import Insights, Media, MediaGone, Profile, ProviderError, SocialProvider, TokenInvalid, TokenSet

GRAPH = "https://graph.instagram.com"


class InstagramLive(SocialProvider):
    platform = "instagram"
    scopes = ["instagram_business_basic", "instagram_business_manage_insights"]

    def __init__(self):
        self.http = httpx.Client(timeout=20)

    def _get(self, path: str, **params):
        r = self.http.get(f"{GRAPH}{path}", params=params)
        if r.status_code in (400, 401) and "OAuthException" in r.text:
            raise TokenInvalid("invalid_token", r.text[:200])
        if r.status_code == 404:
            raise MediaGone("media_gone", r.text[:200])
        if r.status_code == 429:
            raise ProviderError("rate_limited", "Instagram rate limit")
        r.raise_for_status()
        return r.json()

    def authorize_url(self, state: str, redirect_uri: str) -> str:
        return "https://www.instagram.com/oauth/authorize?" + urlencode({
            "client_id": settings.instagram_client_id, "redirect_uri": redirect_uri,
            "scope": ",".join(self.scopes), "response_type": "code", "state": state})

    def exchange_code(self, code: str, redirect_uri: str) -> TokenSet:
        r = self.http.post("https://api.instagram.com/oauth/access_token", data={
            "client_id": settings.instagram_client_id, "client_secret": settings.instagram_client_secret,
            "grant_type": "authorization_code", "redirect_uri": redirect_uri, "code": code})
        r.raise_for_status()
        short = r.json()["access_token"]
        long = self._get("/access_token", grant_type="ig_exchange_token",
                         client_secret=settings.instagram_client_secret, access_token=short)
        return TokenSet(long["access_token"], None, now() + timedelta(seconds=long.get("expires_in", 5_184_000)),
                        list(self.scopes))

    def refresh(self, token: TokenSet) -> TokenSet:
        d = self._get("/refresh_access_token", grant_type="ig_refresh_token", access_token=token.access_token)
        return TokenSet(d["access_token"], None, now() + timedelta(seconds=d.get("expires_in", 5_184_000)), token.scopes)

    def profile(self, access_token: str) -> Profile:
        d = self._get("/me", fields="user_id,username,account_type,followers_count,media_count",
                      access_token=access_token)
        return Profile(external_id=str(d["user_id"]), handle=d["username"], account_type=d["account_type"],
                       followers=d.get("followers_count", 0), media_count=d.get("media_count", 0))

    def list_media(self, access_token: str, limit: int = 30) -> list[Media]:
        d = self._get("/me/media", access_token=access_token, limit=limit,
                      fields="id,caption,media_type,media_product_type,permalink,thumbnail_url,timestamp")
        from datetime import datetime
        return [Media(id=m["id"], caption=m.get("caption", ""), media_type=m["media_type"],
                      media_product_type=m.get("media_product_type", ""), permalink=m["permalink"],
                      thumbnail_url=m.get("thumbnail_url"),
                      timestamp=datetime.fromisoformat(m["timestamp"].replace("+0000", "+00:00")),
                      duration_s=None, owner_external_id="me") for m in d.get("data", [])]

    def find_media_by_permalink(self, access_token: str, permalink: str) -> Media | None:
        target = permalink.split("?")[0].rstrip("/").lower()
        for m in self.list_media(access_token, limit=100):
            if m.permalink.split("?")[0].rstrip("/").lower() == target:
                return m
        return None

    def insights(self, access_token: str, media_id: str) -> Insights:
        d = self._get(f"/{media_id}/insights", access_token=access_token,
                      metric="views,reach,likes,comments,shares,saved,total_interactions")
        v = {x["name"]: x["values"][0]["value"] for x in d.get("data", [])}
        return Insights(views=v.get("views", 0), reach=v.get("reach", 0), likes=v.get("likes", 0),
                        comments=v.get("comments", 0), saves=v.get("saved", 0), shares=v.get("shares", 0), raw=d)

    def online_followers(self, access_token: str):
        try:
            d = self._get("/me/insights", metric="online_followers", period="lifetime", access_token=access_token)
            vals = d["data"][0]["values"][-1]["value"]
            return {int(h): int(c) for h, c in vals.items()}
        except Exception:
            return None  # [Guessing] in the PRD: may not exist under Instagram Login

    def comment_sample(self, access_token: str, media_id: str) -> list[str]:
        d = self._get(f"/{media_id}/comments", fields="text", access_token=access_token, limit=50)
        return [c.get("text", "") for c in d.get("data", [])]
