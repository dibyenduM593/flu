"""Business Login for Instagram adapter against mocked graph.instagram.com responses, plus an audit of a real
account running alongside simulated demo accounts."""
from urllib.parse import parse_qs

import httpx
import pytest

from app.providers.base import MediaGone, ProviderError, ProviderUnavailable, TokenInvalid, TokenSet
from app.providers.instagram_live import InstagramLive, shortcode


def graph_error(code, sub=None, status=400):
    err = {"message": f"error {code}", "type": "OAuthException", "code": code}
    if sub:
        err["error_subcode"] = sub
    return httpx.Response(status, json={"error": err})


REELS = [
    {"id": f"1790000000000000{i}", "caption": f"Night routine part {i} #skincare", "media_type": "VIDEO",
     "permalink": f"https://www.instagram.com/reel/ABC{i}xyz/", "timestamp": f"2026-10-0{i + 1}T14:0{i}:00+0000",
     "like_count": 100 * i, "comments_count": 5 * i}
    for i in range(1, 6)
] + [{"id": "17900000000000099", "caption": "Carousel of products", "media_type": "CAROUSEL_ALBUM",
      "permalink": "https://www.instagram.com/p/CAROUSEL1/", "timestamp": "2026-10-07T10:00:00+0000"}]


class FakeGraph:
    """Routes requests the way graph.instagram.com / api.instagram.com would answer them."""

    def __init__(self, granted="instagram_business_basic,instagram_business_manage_insights", product_type_field=True):
        self.granted, self.product_type_field, self.calls = granted, product_type_field, []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        q = {k: v[0] for k, v in parse_qs(req.url.query.decode()).items()}
        path = req.url.path
        self.calls.append((req.method, req.url.host, path, q))
        if req.url.host == "api.instagram.com":
            body = parse_qs(req.content.decode())
            assert body["grant_type"] == ["authorization_code"] and body["code"] == ["the-code"]
            return httpx.Response(200, json={"data": [{"access_token": "short", "user_id": "17841400000000001",
                                                      "permissions": self.granted}]})
        if path == "/access_token":
            assert q["grant_type"] == "ig_exchange_token" and q["access_token"] == "short"
            return httpx.Response(200, json={"access_token": "long-lived", "token_type": "bearer", "expires_in": 5183944})
        if path == "/refresh_access_token":
            return httpx.Response(200, json={"access_token": "refreshed", "token_type": "bearer", "expires_in": 5183944})
        if q.get("access_token") == "expired":
            return graph_error(190)
        if path.endswith("/me"):
            return httpx.Response(200, json={"id": "app-scoped", "user_id": "17841400000000001", "username": "real.creator",
                                             "account_type": "MEDIA_CREATOR", "followers_count": 5200, "media_count": 6})
        if path.endswith("/me/insights") and q["metric"] == "follower_count":
            return httpx.Response(200, json={"data": [{"name": "follower_count", "period": "day",
                                                       "values": [{"value": 10}] * 20}]})
        if path.endswith("/me/insights") and q["metric"] == "online_followers":
            return httpx.Response(200, json={"data": [{"name": "online_followers", "values": [
                {"value": {str(h): 50 + h for h in range(24)}}]}]})
        if path.endswith("/me/media"):
            if "media_product_type" in q["fields"] and not self.product_type_field:
                return graph_error(100)
            start = int(q.get("after", 0))
            page = REELS[start:start + 3]
            more = start + 3 < len(REELS)
            paging = {"cursors": {"after": str(start + 3)}, **({"next": "https://graph.instagram.com/next"} if more else {})}
            return httpx.Response(200, json={"data": page, "paging": paging})
        if path.endswith("/insights"):
            media_id = path.split("/")[-2]
            if media_id == "17900000000000099":
                return graph_error(100)  # no insights for this album in either metric set
            if media_id == "17900000000000005" and "views" in q["metric"]:
                return graph_error(100)  # older post: falls back to the set without views
            if media_id == "gone":
                return graph_error(100, 33)
            if media_id == "throttled":
                return graph_error(4)
            i = int(media_id[-1])
            vals = {"views": 4000 * i, "reach": 3000 * i, "likes": 100 * i, "comments": 5 * i, "shares": 20 * i,
                    "saved": 30 * i, "total_interactions": 155 * i}
            return httpx.Response(200, json={"data": [{"name": m, "period": "lifetime", "values": [{"value": vals[m]}]}
                                                      for m in q["metric"].split(",")]})
        if path.endswith("/comments"):
            return graph_error(10)  # permission not granted
        return httpx.Response(404, json={"error": {"message": "unexpected " + path, "code": 803}})


@pytest.fixture
def ig():
    graph = FakeGraph()
    return InstagramLive(transport=httpx.MockTransport(graph)), graph


def test_authorize_url_has_scopes_and_state(ig):
    url = ig[0].authorize_url("st", "http://127.0.0.1:8000/v1/connections/instagram/callback")
    assert url.startswith("https://www.instagram.com/oauth/authorize?")
    assert "instagram_business_manage_insights" in url and "state=st" in url and "response_type=code" in url


def test_exchange_code_reads_data_array_and_upgrades_to_long_lived(ig):
    tok = ig[0].exchange_code("the-code", "http://127.0.0.1:8000/v1/connections/instagram/callback")
    assert tok.access_token == "long-lived"
    assert "instagram_business_manage_insights" in tok.scopes
    assert tok.expires_at is not None


def test_exchange_code_refuses_when_insights_permission_unticked():
    prov = InstagramLive(transport=httpx.MockTransport(FakeGraph(granted="instagram_business_basic")))
    with pytest.raises(ProviderError) as e:
        prov.exchange_code("the-code", "x")
    assert e.value.code == "insights_not_granted"


def test_profile_and_follower_growth(ig):
    p = ig[0].profile("long-lived")
    assert (p.external_id, p.handle, p.account_type, p.followers) == ("17841400000000001", "real.creator", "MEDIA_CREATOR", 5200)
    assert p.followers_30d_ago == 5200 - 200


def test_list_media_pages_and_infers_product_type():
    prov = InstagramLive(transport=httpx.MockTransport(FakeGraph(product_type_field=False)))
    media = prov.list_media("long-lived", limit=30)
    assert len(media) == 6
    assert media[0].media_product_type == "REELS" and media[-1].media_product_type == "FEED"
    assert media[0].timestamp.tzinfo is not None


def test_insights_full_fallback_and_unavailable(ig):
    prov = ig[0]
    full = prov.insights("long-lived", "17900000000000002")
    assert (full.views, full.reach, full.saves) == (8000, 6000, 60)
    older = prov.insights("long-lived", "17900000000000005")
    assert older.views == older.reach == 15000  # no `views` metric: reach stands in
    with pytest.raises(ProviderError) as e:
        prov.insights("long-lived", "17900000000000099")
    assert e.value.code == "insights_unavailable"


def test_error_mapping(ig):
    prov = ig[0]
    with pytest.raises(TokenInvalid):
        prov.profile("expired")
    with pytest.raises(MediaGone):
        prov.insights("long-lived", "gone")
    with pytest.raises(ProviderUnavailable):
        prov.insights("long-lived", "throttled")
    with pytest.raises(ProviderError):
        prov.comment_sample("long-lived", "17900000000000001")


def test_permalink_matching_by_shortcode(ig):
    assert shortcode("https://instagram.com/reels/ABC3xyz/?igsh=abc") == "ABC3xyz"
    assert shortcode("https://www.instagram.com/real.creator/reel/ABC3xyz") == "ABC3xyz"
    m = ig[0].find_media_by_permalink("long-lived", "https://www.instagram.com/reels/ABC3xyz/?igsh=MWQ")
    assert m is not None and m.id == "17900000000000003"
    assert ig[0].find_media_by_permalink("long-lived", "https://www.instagram.com/reel/NOPE/") is None


def test_refresh(ig):
    t = ig[0].refresh(TokenSet("long-lived", None, None, []))
    assert t.access_token == "refreshed"


def test_real_account_audit_alongside_demo_accounts(db, monkeypatch):
    """A creator connects a real account: the audit reads it through the live adapter while seeded accounts keep
    using the simulator."""
    from app import providers
    from app.models import AccountAudit, CreatorProfile, FakeAccount, PlatformAccount, User
    from app.providers.fake_social import FakeInstagram
    from app.security import encrypt_token
    from app.services import audit

    graph = FakeGraph()
    real_social = providers.social

    def social(platform, db_, force_live=False):
        if force_live:
            return InstagramLive(transport=httpx.MockTransport(graph))
        return real_social(platform, db_, force_live)

    monkeypatch.setattr(providers, "social", social)

    demo = db.query(PlatformAccount).filter_by(platform="instagram").first()
    assert db.get(FakeAccount, demo.external_id) is not None
    assert isinstance(providers.social_for(demo, db), FakeInstagram)

    u = User(phone="+919876500001", role="creator")
    db.add(u)
    db.flush()
    db.add(CreatorProfile(user_id=u.id, display_name="Real Creator", city="Pune"))
    acc = PlatformAccount(creator_id=u.id, platform="instagram", external_id="17841400000000001", handle="real.creator",
                          access_token_enc=encrypt_token("long-lived"), status="active", scopes=[])
    db.add(acc)
    db.commit()
    assert isinstance(providers.social_for(acc, db), InstagramLive)

    audit.run(db, acc.id)
    a = db.query(AccountAudit).filter_by(platform_account_id=acc.id).one()
    assert a.result == "pass" and a.fraud_flags == []
    assert a.metrics["followers"] == 5200
    assert a.metrics["posts_analysed"] == 5 and a.metrics["posts_without_insights"] == 1
    assert a.metrics["median_views"] == 12000
    cp = db.get(CreatorProfile, u.id)
    assert cp.eligible and float(cp.score) > 0 and "skincare" in cp.niches
    assert any(c[2].endswith("/me/media") for c in graph.calls)
