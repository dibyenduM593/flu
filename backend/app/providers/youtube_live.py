"""YouTube Data API v3 + Analytics API v2. Untested until Google OAuth verification for the
sensitive scopes is granted; endpoint shapes follow the PRD."""
import re
from datetime import datetime, timedelta
from urllib.parse import urlencode

import httpx

from ..clock import now
from ..config import settings
from .base import Insights, Media, MediaGone, Profile, SocialProvider, TokenInvalid, TokenSet

YT = "https://www.googleapis.com/youtube/v3"


def _iso_duration(s: str) -> int:
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m:
        return 0
    h, mi, se = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + se


class YouTubeLive(SocialProvider):
    platform = "youtube"
    scopes = ["https://www.googleapis.com/auth/youtube.readonly",
              "https://www.googleapis.com/auth/yt-analytics.readonly"]

    def __init__(self):
        self.http = httpx.Client(timeout=20)

    def _get(self, url: str, token: str | None = None, **params):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        if not token:
            params["key"] = settings.youtube_api_key
        r = self.http.get(url, params=params, headers=headers)
        if r.status_code == 401:
            raise TokenInvalid("invalid_token", r.text[:200])
        r.raise_for_status()
        return r.json()

    def authorize_url(self, state: str, redirect_uri: str) -> str:
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
            "client_id": settings.google_client_id, "redirect_uri": redirect_uri, "response_type": "code",
            "scope": " ".join(self.scopes), "access_type": "offline", "prompt": "consent", "state": state})

    def exchange_code(self, code: str, redirect_uri: str) -> TokenSet:
        r = self.http.post("https://oauth2.googleapis.com/token", data={
            "code": code, "client_id": settings.google_client_id, "client_secret": settings.google_client_secret,
            "redirect_uri": redirect_uri, "grant_type": "authorization_code"})
        r.raise_for_status()
        d = r.json()
        return TokenSet(d["access_token"], d.get("refresh_token"), now() + timedelta(seconds=d["expires_in"]),
                        d.get("scope", "").split())

    def refresh(self, token: TokenSet) -> TokenSet:
        r = self.http.post("https://oauth2.googleapis.com/token", data={
            "client_id": settings.google_client_id, "client_secret": settings.google_client_secret,
            "refresh_token": token.refresh_token, "grant_type": "refresh_token"})
        if r.status_code == 400 and "invalid_grant" in r.text:
            raise TokenInvalid("invalid_grant", "refresh token revoked")
        r.raise_for_status()
        d = r.json()
        return TokenSet(d["access_token"], token.refresh_token, now() + timedelta(seconds=d["expires_in"]), token.scopes)

    def _channel(self, token: str) -> dict:
        return self._get(f"{YT}/channels", token, part="snippet,statistics,contentDetails", mine="true")["items"][0]

    def profile(self, access_token: str) -> Profile:
        c = self._channel(access_token)
        return Profile(external_id=c["id"], handle=c["snippet"].get("customUrl", c["snippet"]["title"]),
                       account_type="CHANNEL", followers=int(c["statistics"].get("subscriberCount", 0)),
                       media_count=int(c["statistics"].get("videoCount", 0)))

    def list_media(self, access_token: str, limit: int = 30) -> list[Media]:
        c = self._channel(access_token)
        uploads = c["contentDetails"]["relatedPlaylists"]["uploads"]
        items = self._get(f"{YT}/playlistItems", access_token, part="contentDetails,snippet",
                          playlistId=uploads, maxResults=min(limit, 50))["items"]
        ids = [i["contentDetails"]["videoId"] for i in items]
        vids = self._get(f"{YT}/videos", access_token, part="snippet,contentDetails", id=",".join(ids))["items"]
        out = []
        for v in vids:
            dur = _iso_duration(v["contentDetails"]["duration"])
            out.append(Media(id=v["id"], caption=v["snippet"]["title"], media_type="VIDEO",
                             media_product_type="SHORTS" if dur <= 180 else "VIDEO",
                             permalink=f"https://www.youtube.com/shorts/{v['id']}", thumbnail_url=None,
                             timestamp=datetime.fromisoformat(v["snippet"]["publishedAt"].replace("Z", "+00:00")),
                             duration_s=dur, owner_external_id=v["snippet"]["channelId"]))
        return out

    def find_media_by_permalink(self, access_token: str, permalink: str) -> Media | None:
        vid = permalink.rstrip("/").split("/")[-1].split("v=")[-1]
        items = self._get(f"{YT}/videos", None, part="snippet,contentDetails", id=vid)["items"]
        if not items or items[0]["snippet"]["channelId"] != self._channel(access_token)["id"]:
            return None
        v = items[0]
        return Media(id=v["id"], caption=v["snippet"]["title"], media_type="VIDEO", media_product_type="SHORTS",
                     permalink=permalink, thumbnail_url=None,
                     timestamp=datetime.fromisoformat(v["snippet"]["publishedAt"].replace("Z", "+00:00")),
                     duration_s=_iso_duration(v["contentDetails"]["duration"]),
                     owner_external_id=v["snippet"]["channelId"])

    def insights(self, access_token: str, media_id: str) -> Insights:
        # videos.list works with an API key for public videos: tracking needs no creator token.
        items = self._get(f"{YT}/videos", None, part="statistics", id=media_id)["items"]
        if not items:
            raise MediaGone("media_gone", "video removed or private")
        s = items[0]["statistics"]
        views = int(s.get("viewCount", 0))
        return Insights(views=views, reach=views, likes=int(s.get("likeCount", 0)),
                        comments=int(s.get("commentCount", 0)), saves=0, shares=0, raw=items[0])

    def online_followers(self, access_token: str):
        return None

    def comment_sample(self, access_token: str, media_id: str) -> list[str]:
        d = self._get(f"{YT}/commentThreads", None, part="snippet", videoId=media_id, maxResults=50)
        return [i["snippet"]["topLevelComment"]["snippet"]["textOriginal"] for i in d.get("items", [])]
