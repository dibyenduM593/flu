"""HTTP-level flow: OTP login, role scoping, apply, accept with idempotency, publish gate."""
from fastapi.testclient import TestClient


def login(client, phone, role=None):
    r = client.post("/v1/auth/otp/send", json={"phone": phone})
    assert r.status_code == 200, r.text
    otp = r.json()["dev_otp"]
    r = client.post("/v1/auth/otp/verify", json={"phone": phone, "otp": otp, "role": role})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_full_apply_accept_flow(seeded):
    from app.main import app
    with TestClient(app) as c:
        riya = login(c, "+919000000001")
        arjun = login(c, "+919000000002")
        assert c.get("/v1/ops/queue", headers=riya).status_code == 403

        feed = c.get("/v1/creator/briefs", headers=riya).json()
        lip = next(b for b in feed["data"] if b["title"] == "Winter Lip Care")
        assert lip["expected"]["per_deliverable_paise"] > 0
        assert any(b["title"].startswith("Glow Serum") for b in feed["locked"])  # Gold-only brief stays locked

        r = c.post(f"/v1/briefs/{lip['id']}/applications", json={"pitch": "Dupe-or-dud is my best format."}, headers=riya)
        assert r.status_code == 200, r.text
        app_id = r.json()["id"]
        assert c.post(f"/v1/briefs/{lip['id']}/applications", json={"pitch": "again please"}, headers=riya).status_code == 409

        apps = c.get(f"/v1/briefs/{lip['id']}/applications", headers=arjun).json()["data"]
        assert apps == sorted(apps, key=lambda a: -a["rank_score"])

        assert c.post(f"/v1/applications/{app_id}/accept", headers=arjun).status_code == 400  # Idempotency-Key required
        h = {**arjun, "Idempotency-Key": "accept-riya-1"}
        r1 = c.post(f"/v1/applications/{app_id}/accept", headers=h)
        r2 = c.post(f"/v1/applications/{app_id}/accept", headers=h)
        assert r1.status_code == 200 and r1.json() == r2.json()

        hires = c.get("/v1/creator/hires", headers=riya).json()["data"]
        hire = next(x for x in hires if x["brief"]["id"] == lip["id"])
        bad = c.post(f"/v1/hires/{hire['id']}/deliverables", json={"post_url": "https://www.instagram.com/reel/nope/"}, headers=riya)
        assert bad.status_code == 409  # contract not accepted yet
        c.post(f"/v1/hires/{hire['id']}/contract/accept", headers=riya)
        pub = c.post("/v1/dev/social/publish", json={"caption": "Winter lips sorted @kesarinaturals #ad"}, headers=riya).json()
        miss = c.post(f"/v1/hires/{hire['id']}/deliverables", json={"post_url": pub["permalink"]}, headers=riya)
        assert miss.status_code == 422 and miss.json()["error"]["code"] == "required_elements_missing"  # no KESARI10
        pub = c.post("/v1/dev/social/publish", json={"caption": "Winter lips sorted, code KESARI10 @kesarinaturals #ad"},
                     headers=riya).json()
        ok = c.post(f"/v1/hires/{hire['id']}/deliverables", json={"post_url": pub["permalink"]}, headers=riya)
        assert ok.status_code == 200, ok.text
        assert ok.json()["status"] == "submitted"


def test_publish_requires_funded_wallet(seeded):
    from app.main import app
    with TestClient(app) as c:
        arjun = login(c, "+919000000002")
        me = c.get("/v1/me", headers=arjun).json()
        org = me["orgs"][0]["id"]
        b = c.post(f"/v1/orgs/{org}/briefs", headers=arjun, json={
            "title": "Huge brief", "product": "Lip balm", "pay_model": "cpm", "cpm_paise": 5000,
            "cap_paise": 50_000_000, "max_creators": 50, "niches": ["skincare"]}).json()
        r = c.post(f"/v1/briefs/{b['id']}/publish", headers=arjun)
        assert r.status_code == 409 and r.json()["error"]["code"] == "wallet_insufficient"

        bad = c.post(f"/v1/orgs/{org}/briefs", headers=arjun, json={
            "title": "Miracle", "product": "This balm cures cracked lips permanently", "pay_model": "flat",
            "flat_paise": 300000, "max_creators": 1}).json()
        r = c.post(f"/v1/briefs/{bad['id']}/publish", headers=arjun)
        assert r.status_code == 422 and r.json()["error"]["code"] == "policy_blocked"
