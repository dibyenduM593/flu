from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import Principal, creator, current
from ..errors import ApiError
from ..models import Notification, PlatformAccount
from ..services import connections, identity

router = APIRouter(prefix="/v1", tags=["identity"])


class OtpSend(BaseModel):
    phone: str


class OtpVerify(BaseModel):
    phone: str
    otp: str
    role: str | None = None


class Refresh(BaseModel):
    refresh_token: str


@router.post("/auth/otp/send")
def otp_send(body: OtpSend, db: Session = Depends(get_db)):
    return identity.send_otp(db, body.phone)


@router.post("/auth/otp/verify")
def otp_verify(body: OtpVerify, db: Session = Depends(get_db)):
    return identity.verify_otp(db, body.phone, body.otp, body.role)


@router.post("/auth/refresh")
def auth_refresh(body: Refresh, db: Session = Depends(get_db)):
    return identity.refresh(db, body.refresh_token)


@router.get("/me")
def me(p: Principal = Depends(current)):
    return identity.me(p.db, p.user)


@router.get("/me/notifications")
def notifications(p: Principal = Depends(current)):
    rows = (p.db.query(Notification).filter_by(user_id=p.id).order_by(Notification.created_at.desc()).limit(50).all())
    return {"data": [{"id": n.id, "template": n.template, "title": n.title, "body": n.body, "link": n.link,
                      "read": n.read, "created_at": n.created_at} for n in rows],
            "unread": p.db.query(Notification).filter_by(user_id=p.id, read=False).count()}


@router.post("/me/notifications/read")
def notifications_read(p: Principal = Depends(current)):
    p.db.query(Notification).filter_by(user_id=p.id, read=False).update({"read": True})
    p.db.commit()
    return {"ok": True}


# ---- platform connections (CR-2)
@router.post("/connections/{platform}/start")
def connection_start(platform: str, p: Principal = Depends(creator)):
    return connections.start(p.db, p.id, platform)


@router.get("/connections/{platform}/callback", include_in_schema=True)
def connection_callback(platform: str, code: str | None = None, state: str | None = None,
                        error: str | None = None, db: Session = Depends(get_db)):
    dest = f"{settings.web_origin}/creator/accounts"
    if error or not code or not state:
        return RedirectResponse(f"{dest}?error={error or 'cancelled'}")
    try:
        acc = connections.callback(db, platform, code, state)
    except ApiError as e:
        return RedirectResponse(f"{dest}?error={e.code}")
    return RedirectResponse(f"{dest}?connected={platform}&handle={acc.handle}")


@router.get("/connections")
def connection_list(p: Principal = Depends(creator)):
    return {"data": [connections.public(a) for a in p.db.query(PlatformAccount).filter_by(creator_id=p.id).all()]}


@router.delete("/connections/{account_id}")
def connection_delete(account_id: str, p: Principal = Depends(creator)):
    connections.revoke(p.db, p.id, account_id)
    return {"ok": True}
