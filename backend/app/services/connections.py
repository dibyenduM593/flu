"""OAuth linking, encrypted token storage and token refresh (CR-2, connections package).

Only this module decrypts platform tokens; no API response ever includes them."""
from datetime import timedelta

from sqlalchemy.orm import Session

from .. import providers
from ..clock import now
from ..config import settings
from ..errors import bad, conflict, not_found
from ..models import Deliverable, MediaItem, PlatformAccount
from ..providers.base import ProviderError, TokenInvalid, TokenSet
from ..security import decrypt_token, encrypt_token, read_state, sign_state
from . import jobs
from .ops import audit, notify

PLATFORMS = ("instagram", "youtube")


def redirect_uri(platform: str) -> str:
    if platform == "instagram" and settings.instagram_redirect_uri:
        return settings.instagram_redirect_uri  # e.g. an HTTPS tunnel registered in the Meta App Dashboard
    return f"{settings.api_origin}/v1/connections/{platform}/callback"


def start(db: Session, creator_id: str, platform: str) -> dict:
    if platform not in PLATFORMS:
        raise bad("unsupported_platform", "only Instagram and YouTube are supported")
    mode = providers.social_mode(platform)
    if mode == "live" and platform == "instagram" and not (settings.instagram_client_id and settings.instagram_client_secret):
        raise bad("instagram_not_configured", "Set INSTAGRAM_CLIENT_ID and INSTAGRAM_CLIENT_SECRET in backend/.env, then restart the API.")
    state = sign_state({"uid": creator_id, "platform": platform, "mode": mode})
    return {"url": providers.social(platform, db).authorize_url(state, redirect_uri(platform)), "state": state,
            "mode": mode}


def callback(db: Session, platform: str, code: str, state: str) -> PlatformAccount:
    try:
        st = read_state(state)
    except Exception:
        raise bad("invalid_state", "connection link expired; start again")
    if st.get("platform") != platform:
        raise bad("invalid_state", "platform mismatch")
    # The mode is fixed when the flow starts, so a code from the simulator is never sent to Meta (and vice versa).
    prov = providers.social(platform, db, force_live=st.get("mode") == "live", force_fake=st.get("mode") == "fake")
    try:
        tok = prov.exchange_code(code, redirect_uri(platform))
        prof = prov.profile(tok.access_token)
    except ProviderError as e:
        raise bad(e.code, str(e) or "the platform rejected the connection")
    if platform == "instagram" and prof.account_type not in ("BUSINESS", "MEDIA_CREATOR"):
        raise bad("personal_account", "Switch to a Creator account in Instagram settings, then connect again.")
    acc = db.query(PlatformAccount).filter_by(platform=platform, external_id=prof.external_id).first()
    if acc and acc.creator_id != st["uid"] and acc.status != "revoked":
        raise conflict("account_taken", "this account is already connected to another Flu creator")
    if not acc:
        acc = PlatformAccount(creator_id=st["uid"], platform=platform, external_id=prof.external_id, handle=prof.handle)
        db.add(acc)
    acc.creator_id = st["uid"]
    acc.handle, acc.account_type, acc.follower_count = prof.handle, prof.account_type, prof.followers
    acc.access_token_enc, acc.refresh_token_enc = encrypt_token(tok.access_token), encrypt_token(tok.refresh_token)
    acc.token_expires_at, acc.token_issued_at, acc.scopes = tok.expires_at, now(), tok.scopes
    acc.status, acc.connected_at = "active", now()
    db.flush()
    audit(db, st["uid"], "connection.linked", "platform_account", acc.id, None,
          {"platform": platform, "handle": prof.handle})
    jobs.enqueue(db, "audit.run", {"platform_account_id": acc.id})
    db.commit()
    return acc


def access_token(db: Session, acc: PlatformAccount) -> str:
    """Decrypt (inside workers/services only), refreshing when close to expiry."""
    if acc.status != "active":
        raise TokenInvalid("needs_reauth", f"{acc.platform} account needs reconnecting")
    tok = TokenSet(decrypt_token(acc.access_token_enc), decrypt_token(acc.refresh_token_enc), acc.token_expires_at,
                   acc.scopes)
    t = now()
    soon = timedelta(days=10) if acc.platform == "instagram" else timedelta(minutes=5)
    if acc.token_expires_at and acc.token_expires_at - t < soon:
        refresh_account(db, acc)
        tok.access_token = decrypt_token(acc.access_token_enc)
    return tok.access_token


def refresh_account(db: Session, acc: PlatformAccount):
    prov = providers.social_for(acc, db)
    tok = TokenSet(decrypt_token(acc.access_token_enc), decrypt_token(acc.refresh_token_enc), acc.token_expires_at,
                   acc.scopes)
    if acc.platform == "instagram" and acc.token_issued_at and now() - acc.token_issued_at < timedelta(hours=24):
        return  # IG refresh requires a token at least 24 h old
    try:
        new = prov.refresh(tok)
    except TokenInvalid:
        mark_needs_reauth(db, acc)
        raise
    acc.access_token_enc = encrypt_token(new.access_token)
    if new.refresh_token:
        acc.refresh_token_enc = encrypt_token(new.refresh_token)
    acc.token_expires_at, acc.token_issued_at = new.expires_at, now()


def mark_needs_reauth(db: Session, acc: PlatformAccount):
    if acc.status != "needs_reauth":
        acc.status = "needs_reauth"
        notify(db, acc.creator_id, "needs_reauth", f"Reconnect @{acc.handle} on {acc.platform} to keep tracking.",
               "/creator/accounts")


@jobs.task("connections.refresh_tokens")
def refresh_tokens_job(db: Session):
    """Daily: refresh Instagram tokens from day 50; alert at day 55 (60-day tokens)."""
    t = now()
    for acc in db.query(PlatformAccount).filter_by(status="active").all():
        if acc.platform == "instagram" and acc.token_issued_at and t - acc.token_issued_at >= timedelta(days=50):
            try:
                refresh_account(db, acc)
            except TokenInvalid:
                pass
            if acc.token_issued_at and t - acc.token_issued_at >= timedelta(days=55):
                notify(db, acc.creator_id, "needs_reauth", "Your Instagram connection expires in 5 days.",
                       "/creator/accounts")
    db.commit()


def revoke(db: Session, creator_id: str, account_id: str):
    acc = db.get(PlatformAccount, account_id)
    if not acc or acc.creator_id != creator_id:
        raise not_found("connection")
    acc.status = "revoked"
    acc.access_token_enc = acc.refresh_token_enc = None
    # Purge media not tied to a deliverable (deliverables are kept: they back payouts).
    kept = {d.media_item_id for d in db.query(Deliverable).all()}
    for m in db.query(MediaItem).filter_by(platform_account_id=acc.id).all():
        if m.id not in kept:
            db.delete(m)
    audit(db, creator_id, "connection.revoked", "platform_account", acc.id)
    db.commit()


def public(acc: PlatformAccount) -> dict:
    return {"id": acc.id, "platform": acc.platform, "handle": acc.handle, "account_type": acc.account_type,
            "follower_count": acc.follower_count, "status": acc.status, "scopes": acc.scopes,
            "connected_at": acc.connected_at, "last_synced_at": acc.last_synced_at,
            "token_expires_at": acc.token_expires_at}
