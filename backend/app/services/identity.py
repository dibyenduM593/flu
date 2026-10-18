"""Phone-OTP auth with rotating refresh tokens (CR-1)."""
import re
from datetime import timedelta

from sqlalchemy.orm import Session

from .. import providers
from ..clock import now
from ..config import settings
from ..db import uuid7
from ..errors import ApiError, bad
from ..models import CreatorProfile, OrgMember, OtpCode, Org, RefreshToken, User
from ..security import decode, hash_otp, issue_access, issue_refresh

PHONE_RE = re.compile(r"^\+91[6-9]\d{9}$")


def normalize_phone(phone: str) -> str:
    digits = re.sub(r"[^\d+]", "", phone or "")
    if digits.startswith("0"):
        digits = digits[1:]
    if not digits.startswith("+"):
        digits = "+91" + digits[-10:]
    if not PHONE_RE.match(digits):
        raise bad("invalid_phone", "enter a 10-digit Indian mobile number")
    return digits


def send_otp(db: Session, phone: str) -> dict:
    phone = normalize_phone(phone)
    recent = db.query(OtpCode).filter(OtpCode.phone == phone,
                                      OtpCode.created_at >= now() - timedelta(minutes=10)).count()
    if recent >= settings.otp_per_10min:
        raise ApiError(429, "otp_rate_limited", "too many OTP requests; try again in 10 minutes")
    code = providers.otp().send(phone)
    db.add(OtpCode(phone=phone, code_hash=hash_otp(phone, code), expires_at=now() + timedelta(minutes=5)))
    db.commit()
    exists = db.query(User).filter_by(phone=phone).first() is not None
    out = {"sent": True, "phone": phone, "existing_user": exists}
    if settings.dev_mode:
        out["dev_otp"] = code
    return out


def _tokens(db: Session, user: User) -> dict:
    jti = uuid7()
    db.add(RefreshToken(id=jti, user_id=user.id, expires_at=now() + timedelta(days=settings.refresh_ttl_days)))
    return {"access_token": issue_access(user.id, user.role), "refresh_token": issue_refresh(user.id, jti),
            "user": me(db, user)}


def verify_otp(db: Session, phone: str, otp: str, role: str | None) -> dict:
    phone = normalize_phone(phone)
    row = (db.query(OtpCode).filter_by(phone=phone, consumed=False).order_by(OtpCode.created_at.desc()).first())
    if not row or row.expires_at < now():
        raise bad("otp_expired", "OTP expired; request a new one")
    row.attempts += 1
    if row.attempts > 5:
        row.consumed = True
        db.commit()
        raise ApiError(429, "otp_locked", "too many attempts; request a new OTP")
    if row.code_hash != hash_otp(phone, otp.strip()):
        db.commit()
        raise bad("otp_invalid", "incorrect OTP")
    row.consumed = True
    user = db.query(User).filter_by(phone=phone).first()
    if not user:
        if role not in ("creator", "brand_member"):
            raise bad("role_required", "choose creator or brand to sign up", new_user=True)
        user = User(phone=phone, role=role)
        db.add(user)
        db.flush()
    out = _tokens(db, user)
    db.commit()
    return out


def refresh(db: Session, refresh_token: str) -> dict:
    try:
        data = decode(refresh_token, "refresh")
    except Exception:
        raise ApiError(401, "invalid_refresh", "refresh token invalid or expired")
    row = db.get(RefreshToken, data["jti"])
    if not row or row.revoked:
        # Reuse of a rotated token: revoke the whole family.
        db.query(RefreshToken).filter_by(user_id=data["sub"]).update({"revoked": True})
        db.commit()
        raise ApiError(401, "invalid_refresh", "refresh token reused")
    row.revoked = True
    user = db.get(User, data["sub"])
    out = _tokens(db, user)
    db.commit()
    return out


def me(db: Session, user: User) -> dict:
    out = {"id": user.id, "phone": user.phone[:-6] + "••••" + user.phone[-2:], "role": user.role,
           "creator": None, "orgs": []}
    if user.role == "creator":
        cp = db.get(CreatorProfile, user.id)
        if cp:
            out["creator"] = {"display_name": cp.display_name, "tier": cp.tier, "score": float(cp.score),
                              "city": cp.city, "niches": cp.niches, "kyc_status": cp.kyc_status}
    for m in db.query(OrgMember).filter_by(user_id=user.id).all():
        o = db.get(Org, m.org_id)
        out["orgs"].append({"id": o.id, "name": o.name, "role": m.role, "plan": o.plan, "type": o.type})
    return out
