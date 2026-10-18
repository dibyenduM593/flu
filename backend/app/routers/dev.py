"""Dev-mode simulator endpoints: the fake OAuth consent screen, fake Razorpay checkout, posting to the
simulated Instagram/YouTube, fraud injection and the simulated clock. Not mounted when FLU_DEV_MODE=0."""
from datetime import timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import clock
from ..db import get_db
from ..deps import Principal, creator, current, ops
from ..errors import bad, forbidden, not_found
from ..models import (Deliverable, FakeAccount, FakeMedia, FakeRzpObject, MediaItem, Payment, PlatformAccount)
from ..providers.fake_razorpay import FakeRazorpay
from ..providers.fake_social import _FakeBase
from ..providers.fake_world import ensure_account
from ..security import read_state
from ..services import jobs, money

router = APIRouter(prefix="/v1/dev", tags=["dev"])


class AuthorizeIn(BaseModel):
    platform: str
    handle: str
    account_type: str = "MEDIA_CREATOR"
    state: str
    redirect_uri: str


@router.post("/oauth/authorize")
def authorize(body: AuthorizeIn, db: Session = Depends(get_db)):
    try:
        read_state(body.state)
    except Exception:
        raise bad("invalid_state", "connection link expired; start again")
    if not body.handle.strip():
        raise bad("handle_required", "enter a handle")
    acc = ensure_account(db, body.platform, body.handle,
                         body.account_type if body.platform == "instagram" else "CHANNEL")
    db.commit()
    code = _FakeBase.issue_code(acc.external_id)
    return {"redirect": f"{body.redirect_uri}?{urlencode({'code': code, 'state': body.state})}"}


@router.get("/fake-accounts")
def fake_accounts(platform: str = "instagram", db: Session = Depends(get_db)):
    taken = {a.external_id for a in db.query(PlatformAccount).filter(PlatformAccount.status != "revoked").all()}
    rows = db.query(FakeAccount).filter_by(platform=platform).all()
    return {"data": [{"handle": a.handle, "followers": a.followers, "niche": a.persona.get("niche"),
                      "account_type": a.account_type, "fraud": a.persona.get("fraud")}
                     for a in rows if a.external_id not in taken][:12]}


@router.get("/razorpay/orders/{order_id}")
def order(order_id: str, db: Session = Depends(get_db)):
    row = db.get(FakeRzpObject, order_id)
    if not row:
        raise not_found("order")
    p = db.query(Payment).filter_by(rzp_order_id=order_id).first()
    return {**row.data, "org_id": p.org_id if p else None}


class PayIn(BaseModel):
    order_id: str
    method: str = "upi"
    fail: bool = False


@router.post("/razorpay/pay")
def pay(body: PayIn, db: Session = Depends(get_db)):
    """What Checkout.js + Razorpay's servers do: capture, return the signed response, fire the webhook."""
    rzp = FakeRazorpay(db)
    if body.fail:
        order = db.get(FakeRzpObject, body.order_id).data
        raw, sig = rzp.webhook_for("payment.failed", "payment", {"id": "pay_failed", "order_id": body.order_id,
                                                                  "amount": order["amount"]})
        money.handle_webhook(db, raw, sig)
        return {"status": "failed"}
    resp = rzp.simulate_checkout(body.order_id, body.method)
    pay_entity = rzp.get_payment(resp["razorpay_payment_id"])
    db.commit()
    raw, sig = rzp.webhook_for("payment.captured", "payment", pay_entity)
    money.handle_webhook(db, raw, sig)
    return resp


class PublishIn(BaseModel):
    platform: str = "instagram"
    caption: str
    paid_partnership: bool = False
    quality: float = 1.0


@router.post("/social/publish")
def publish(body: PublishIn, p: Principal = Depends(creator)):
    """Post a new Reel/Short on the creator's simulated account (stands in for posting in the Instagram app)."""
    acc = p.db.query(PlatformAccount).filter_by(creator_id=p.id, platform=body.platform, status="active").first()
    if not acc:
        raise bad("not_connected", f"connect {body.platform} first")
    fa = p.db.get(FakeAccount, acc.external_id)
    from ..providers.fake_world import create_post
    m = create_post(p.db, fa, body.caption, posted_at=clock.now() - timedelta(minutes=2),
                    seed=f"live:{fa.handle}:{clock.now().isoformat()}", quality_boost=max(0.3, min(body.quality, 3)),
                    paid_partnership=body.paid_partnership)
    if body.platform == "youtube":
        m.duration_s = min(m.duration_s, 58)
        m.media_product_type = "SHORTS"
        m.permalink = f"https://www.youtube.com/shorts/{m.shortcode}"
    p.db.commit()
    return {"permalink": m.permalink, "media_id": m.id}


def _fake_media_for(db: Session, deliverable_id: str) -> FakeMedia:
    d = db.get(Deliverable, deliverable_id)
    if not d:
        raise not_found("deliverable")
    m = db.get(MediaItem, d.media_item_id)
    fm = db.get(FakeMedia, m.external_media_id)
    if not fm:
        raise not_found("simulated post")
    return fm


class BotIn(BaseModel):
    views: int = 400_000


@router.post("/social/deliverables/{deliverable_id}/bot-views")
def bot_views(deliverable_id: str, body: BotIn, p: Principal = Depends(ops)):
    fm = _fake_media_for(p.db, deliverable_id)
    fm.bot_views, fm.bot_at = fm.bot_views + body.views, clock.now()
    p.db.commit()
    return {"ok": True, "bot_views": fm.bot_views}


@router.post("/social/deliverables/{deliverable_id}/delete")
def delete_post(deliverable_id: str, p: Principal = Depends(ops)):
    fm = _fake_media_for(p.db, deliverable_id)
    fm.deleted = True
    p.db.commit()
    return {"ok": True}


@router.post("/social/accounts/{account_id}/revoke")
def revoke_token(account_id: str, p: Principal = Depends(ops)):
    acc = p.db.get(PlatformAccount, account_id)
    fa = acc and p.db.get(FakeAccount, acc.external_id)
    if not fa:
        raise not_found("account")
    fa.persona = {**fa.persona, "revoked": True}
    p.db.commit()
    return {"ok": True}


class AdvanceIn(BaseModel):
    hours: float


@router.post("/clock/advance")
def advance(body: AdvanceIn, p: Principal = Depends(current)):
    if p.role != "ops":
        raise forbidden("ops scope required")
    if not 0 < body.hours <= 24 * 45:
        raise bad("invalid_hours", "advance between 0 and 1080 hours")
    p.db.close()
    return jobs.advance(body.hours, step_hours=1.0 if body.hours <= 24 else 2.0 if body.hours <= 96 else 3.0)


@router.post("/jobs/run")
def run_jobs(p: Principal = Depends(ops)):
    return {"ran": jobs.run_due()}


@router.get("/clock")
def get_clock():
    return {"now": clock.now(), "offset_hours": clock.offset_hours()}
