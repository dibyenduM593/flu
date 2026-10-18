"""Auth dependencies and row-level authorisation helpers (assert_org_member, assert_creator_owns)."""
from dataclasses import dataclass

import jwt
from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from .db import get_db
from .errors import ApiError, forbidden, not_found
from .models import CreatorProfile, IdempotencyKey, OrgMember, User
from .security import decode


@dataclass
class Principal:
    user: User
    db: Session

    @property
    def id(self):
        return self.user.id

    @property
    def role(self):
        return self.user.role


def current(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ApiError(401, "unauthenticated", "missing bearer token")
    try:
        data = decode(authorization.split(" ", 1)[1], "access")
    except jwt.ExpiredSignatureError:
        raise ApiError(401, "token_expired", "access token expired")
    except jwt.InvalidTokenError:
        raise ApiError(401, "invalid_token", "invalid access token")
    user = db.get(User, data["sub"])
    if not user or user.status != "active":
        raise ApiError(401, "invalid_token", "user not active")
    return Principal(user=user, db=db)


def creator(p: Principal = Depends(current)) -> Principal:
    if p.role != "creator":
        raise forbidden("creator scope required")
    if not p.db.get(CreatorProfile, p.id):
        raise ApiError(409, "profile_missing", "complete creator onboarding first")
    return p


def brand(p: Principal = Depends(current)) -> Principal:
    if p.role != "brand_member":
        raise forbidden("brand scope required")
    return p


def ops(p: Principal = Depends(current)) -> Principal:
    if p.role != "ops":
        raise forbidden("ops scope required")
    return p


def assert_org_member(db: Session, user_id: str, org_id: str, roles=("owner", "admin", "member")):
    m = db.get(OrgMember, (org_id, user_id))
    if not m or m.role not in roles:
        raise forbidden("not a member of this workspace")
    return m


def user_org_id(db: Session, user_id: str) -> str:
    m = db.query(OrgMember).filter_by(user_id=user_id).first()
    if not m:
        raise ApiError(409, "org_missing", "create a brand workspace first")
    return m.org_id


def assert_creator_owns(owner_id: str, p: Principal):
    if owner_id != p.id:
        raise not_found()


def idempotency_key(idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> str:
    if not idempotency_key:
        raise ApiError(400, "idempotency_key_required", "Idempotency-Key header is required on this endpoint")
    return idempotency_key


def replay_or_none(db: Session, key: str, user_id: str, request: Request):
    row = db.get(IdempotencyKey, f"{user_id}:{key}")
    if row:
        if row.path != request.url.path:
            raise ApiError(422, "idempotency_key_reused", "key was used for a different request")
        return row.response
    return None


def remember(db: Session, key: str, user_id: str, request: Request, response: dict, status: int = 200):
    db.add(IdempotencyKey(key=f"{user_id}:{key}", user_id=user_id, path=request.url.path,
                          status_code=status, response=response))
