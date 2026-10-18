"""Inbound webhooks. Signatures are verified before parsing; unverifiable payloads are quarantined."""
import base64
import hashlib
import hmac
import json
import secrets

from fastapi import APIRouter, Depends, Form, Header, Request
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..errors import bad
from ..models import PlatformAccount
from ..services import money
from ..services.connections import revoke

router = APIRouter(tags=["webhooks"])


@router.post("/webhooks/razorpay")
async def razorpay(request: Request, x_razorpay_signature: str | None = Header(default=None),
                   db: Session = Depends(get_db)):
    raw = (await request.body()).decode()
    return money.handle_webhook(db, raw, x_razorpay_signature)


def _parse_signed_request(signed: str) -> dict:
    try:
        sig_b64, payload_b64 = signed.split(".", 1)
        pad = lambda s: s + "=" * (-len(s) % 4)
        sig = base64.urlsafe_b64decode(pad(sig_b64))
        payload = json.loads(base64.urlsafe_b64decode(pad(payload_b64)))
    except Exception:
        raise bad("invalid_signed_request", "malformed signed_request")
    expected = hmac.new(settings.instagram_client_secret.encode(), payload_b64.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        raise bad("invalid_signature", "signed_request signature mismatch")
    return payload


@router.post("/webhooks/meta/deauth")
def meta_deauth(signed_request: str = Form(...), db: Session = Depends(get_db)):
    data = _parse_signed_request(signed_request)
    acc = db.query(PlatformAccount).filter_by(platform="instagram", external_id=str(data.get("user_id"))).first()
    if acc:
        revoke(db, acc.creator_id, acc.id)
    return {"ok": True}


@router.post("/webhooks/meta/delete")
def meta_delete(signed_request: str = Form(...), db: Session = Depends(get_db)):
    data = _parse_signed_request(signed_request)
    acc = db.query(PlatformAccount).filter_by(platform="instagram", external_id=str(data.get("user_id"))).first()
    code = secrets.token_hex(8)
    if acc:
        revoke(db, acc.creator_id, acc.id)  # tokens revoked now; purge completes within 30 days
    return {"url": f"{settings.web_origin}/deletion?code={code}", "confirmation_code": code}
