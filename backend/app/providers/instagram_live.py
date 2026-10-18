"""Instagram API with Instagram Login ("Business Login for Instagram", graph.instagram.com).

No Facebook Page is needed. In Development mode (Standard Access) only Instagram professional accounts added to
the app in the Meta App Dashboard can authorize; serving other creators needs Advanced Access via App Review.
Endpoints per developers.facebook.com/docs/instagram-platform (Graph v25.0 at the time of writing).
"""
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx

from ..clock import now
from ..config import settings
from .base import (Insights, Media, MediaGone, Profile, ProviderError, ProviderUnavailable, SocialProvider,
                   TokenInvalid, TokenSet)

AUTH_URL = "https://www.instagram.com/oauth/authorize"
CODE_EXCHANGE_URL = "https://api.instagram.com/oauth/access_token"
GRAPH_HOST = "https://graph.instagram.com"
SCOPES = ["instagram_business_basic", "instagram_business_manage_insights"]
MEDIA_FIELDS = "id,caption,media_type,media_product_type,permalink,thumbnail_url,timestamp,like_count,comments_count"
MEDIA_FIELDS_BASIC = "id,caption,media_type,permalink,thumbnail_url,timestamp,like_count,comments_count"
METRICS = "views,reach,likes,comments,shares,saved,total_interactions"
METRICS_FALLBACK = "reach,likes,comments,shares,saved"  # e.g. posts from before `views` existed
TOKEN_ERROR_CODES = {102, 190, 463, 467}
RATE_LIMIT_CODES = {4, 17, 32, 613, 80002}
SHORTCODE_RE = re.compile(r"instagram\.com/(?:[A-Za-z0-9_.]+/)?(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)", re.I)


def shortcode(url: str) -> str | None:
    m = SHORTCODE_RE.search(url or "")
    return m.group(1) if m else None


def _ts(s: str) -> datetime:
    # Graph returns e.g. 2026-10-12T14:03:11+0000
    if s.endswith("+0000"):
        s = s[:-5] + "+00:00"
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def _metric_values(payload: dict) -> dict:
    out = {}
    for row in payload.get("data", []):
        if "total_value" in row:
            out[row["name"]] = row["total_value"].get("value", 0)
        elif row.get("values"):
            out[row["name"]] = row["values"][-1].get("value", 0)
    return out


class InstagramLive(SocialProvider):
    platform = "instagram"
    scopes = SCOPES

    def __init__(self, transport: httpx.BaseTransport | None = None):
        self.http = httpx.Client(timeout=20, transport=transport)
        self.base = f"{GRAPH_HOST}/{settings.instagram_graph_version}"

    # ------------------------------------------------------------------ http
    @staticmethod
    def _raise(r: httpx.Response):
        try:
            err = r.json().get("error", {})
        except ValueError:
            err = {}
        code, sub = err.get("code"), err.get("error_subcode")
        msg = (err.get("message") or r.text or "")[:300]
        if code in TOKEN_ERROR_CODES or r.status_code == 401:
            raise TokenInvalid("invalid_token", msg)
        if code in RATE_LIMIT_CODES or r.status_code == 429 or r.status_code >= 500:
            raise ProviderUnavailable("instagram_unavailable", msg)
        if code == 100 and sub == 33:
            raise MediaGone("media_gone", msg)
        raise ProviderError(f"instagram_error_{code or r.status_code}", msg)

    def _request(self, method: str, url: str, **kw) -> dict:
        try:
            r = self.http.request(method, url, **kw)
        except httpx.HTTPError as e:
            raise ProviderUnavailable("instagram_unreachable", str(e)) from e
        if r.status_code >= 400:
            self._raise(r)
        return r.json()

    def _get(self, path: str, token: str, **params) -> dict:
        return self._request("GET", f"{self.base}{path}", params={**params, "access_token": token})

    # ------------------------------------------------------------------ OAuth
    def authorize_url(self, state: str, redirect_uri: str) -> str:
        return AUTH_URL + "?" + urlencode({
            "client_id": settings.instagram_client_id, "redirect_uri": redirect_uri, "response_type": "code",
            "scope": ",".join(self.scopes), "state": state})

    def exchange_code(self, code: str, redirect_uri: str) -> TokenSet:
        d = self._request("POST", CODE_EXCHANGE_URL, data={
            "client_id": settings.instagram_client_id, "client_secret": settings.instagram_client_secret,
            "grant_type": "authorization_code", "redirect_uri": redirect_uri, "code": code})
        d = d["data"][0] if isinstance(d.get("data"), list) and d["data"] else d  # documented shape is {"data": [...]}
        perms = d.get("permissions") or []
        granted = [p.strip() for p in (perms.split(",") if isinstance(perms, str) else perms) if p.strip()]
        if granted and "instagram_business_manage_insights" not in granted:
            raise ProviderError("insights_not_granted",
                                "Flu needs permission to read your post insights. Connect again and keep it switched on.")
        long = self._request("GET", f"{GRAPH_HOST}/access_token", params={
            "grant_type": "ig_exchange_token", "client_secret": settings.instagram_client_secret,
            "access_token": d["access_token"]})
        return TokenSet(long["access_token"], None, now() + timedelta(seconds=int(long.get("expires_in", 5_184_000))),
                        granted or list(self.scopes))

    def refresh(self, token: TokenSet) -> TokenSet:
        d = self._request("GET", f"{GRAPH_HOST}/refresh_access_token",
                          params={"grant_type": "ig_refresh_token", "access_token": token.access_token})
        return TokenSet(d["access_token"], None, now() + timedelta(seconds=int(d.get("expires_in", 5_184_000))),
                        token.scopes)

    # ------------------------------------------------------------------ account
    def profile(self, access_token: str) -> Profile:
        d = self._get("/me", access_token, fields="user_id,username,account_type,followers_count,media_count")
        followers = int(d.get("followers_count", 0))
        return Profile(external_id=str(d.get("user_id") or d["id"]), handle=d["username"],
                       account_type=d.get("account_type", ""), followers=followers,
                       media_count=int(d.get("media_count", 0)),
                       followers_30d_ago=self._followers_30d_ago(access_token, followers))

    def _followers_30d_ago(self, token: str, followers: int) -> int | None:
        """follower_count is daily new followers, last 30 days only, and needs 100+ followers."""
        if followers < 100:
            return None
        try:
            t = now()
            d = self._get("/me/insights", token, metric="follower_count", period="day",
                          since=int((t - timedelta(days=29)).timestamp()), until=int(t.timestamp()))
            gained = sum(int(v.get("value", 0)) for row in d.get("data", []) for v in row.get("values", []))
            return max(followers - gained, 1)
        except ProviderError:
            return None

    def _media_page(self, token: str, limit: int, after: str | None, fields: str) -> dict:
        params = {"fields": fields, "limit": min(limit, 50)}
        if after:
            params["after"] = after
        return self._get("/me/media", token, **params)

    def list_media(self, access_token: str, limit: int = 30) -> list[Media]:
        out, after, fields = [], None, MEDIA_FIELDS
        while len(out) < limit:
            try:
                page = self._media_page(access_token, limit - len(out), after, fields)
            except ProviderError as e:
                if fields == MEDIA_FIELDS and not isinstance(e, (TokenInvalid, ProviderUnavailable)):
                    fields = MEDIA_FIELDS_BASIC  # media_product_type isn't available on every API flavour
                    continue
                raise
            for m in page.get("data", []):
                mpt = m.get("media_product_type") or ("REELS" if m.get("media_type") == "VIDEO" else "FEED")
                out.append(Media(id=m["id"], caption=m.get("caption", "") or "", media_type=m.get("media_type", ""),
                                 media_product_type=mpt, permalink=m.get("permalink", ""),
                                 thumbnail_url=m.get("thumbnail_url"), timestamp=_ts(m["timestamp"]),
                                 duration_s=None, owner_external_id="me"))
            after = page.get("paging", {}).get("cursors", {}).get("after")
            if not after or not page.get("paging", {}).get("next"):
                break
        return out[:limit]

    def find_media_by_permalink(self, access_token: str, permalink: str) -> Media | None:
        """No lookup-by-URL exists for this API flavour: page through /me/media and match the shortcode."""
        target = shortcode(permalink)
        if not target:
            return None
        for m in self.list_media(access_token, limit=200):
            if shortcode(m.permalink) == target:
                return m
        return None

    def insights(self, access_token: str, media_id: str) -> Insights:
        last: ProviderError | None = None
        for metrics in (METRICS, METRICS_FALLBACK):
            try:
                d = self._get(f"/{media_id}/insights", access_token, metric=metrics)
            except (TokenInvalid, MediaGone, ProviderUnavailable):
                raise
            except ProviderError as e:
                last = e
                continue
            v = _metric_values(d)
            reach = int(v.get("reach", 0))
            return Insights(views=int(v.get("views", reach)), reach=reach, likes=int(v.get("likes", 0)),
                            comments=int(v.get("comments", 0)), saves=int(v.get("saved", 0)),
                            shares=int(v.get("shares", 0)), raw=d)
        raise ProviderError("insights_unavailable", str(last))

    def online_followers(self, access_token: str):
        """Hour-of-day buckets. Meta's docs don't state the time zone of the hour keys; treated as IST (unverified)."""
        try:
            d = self._get("/me/insights", access_token, metric="online_followers", period="lifetime")
            vals = d["data"][0]["values"][-1]["value"]
            return {int(h): int(c) for h, c in vals.items()} or None
        except (ProviderError, KeyError, IndexError):
            return None

    def comment_sample(self, access_token: str, media_id: str) -> list[str]:
        # Needs instagram_business_manage_comments, which Flu doesn't request yet; callers treat failure as "skip".
        d = self._get(f"/{media_id}/comments", access_token, fields="text", limit=50)
        return [c.get("text", "") for c in d.get("data", [])]
