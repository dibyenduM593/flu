"""JWTs, envelope-style token encryption, PAN hashing and webhook signatures."""
import base64
import hashlib
import hmac
import os
import secrets
from datetime import timedelta

import jwt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .clock import now
from .config import settings


# ---- JWT
def issue_access(user_id: str, role: str) -> str:
    t = now()
    return jwt.encode(
        {"sub": user_id, "role": role, "typ": "access", "iat": int(t.timestamp()),
         "exp": int((t + timedelta(minutes=settings.access_ttl_min)).timestamp())},
        settings.jwt_secret, algorithm="HS256",
    )


def issue_refresh(user_id: str, jti: str) -> str:
    t = now()
    return jwt.encode(
        {"sub": user_id, "jti": jti, "typ": "refresh", "iat": int(t.timestamp()),
         "exp": int((t + timedelta(days=settings.refresh_ttl_days)).timestamp())},
        settings.jwt_secret, algorithm="HS256",
    )


def decode(token: str, typ: str) -> dict:
    # Verify exp against the platform clock so simulated time advances expire tokens consistently.
    # PyJWT would also reject an `iat` ahead of real time, which tokens minted on the simulated clock are.
    data = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"],
                      options={"verify_exp": False, "verify_iat": False, "verify_nbf": False})
    if data.get("typ") != typ:
        raise jwt.InvalidTokenError("wrong token type")
    if data["exp"] < now().timestamp():
        raise jwt.ExpiredSignatureError("expired")
    return data


def sign_state(payload: dict, minutes: int = 15) -> str:
    return jwt.encode({**payload, "exp": int((now() + timedelta(minutes=minutes)).timestamp())},
                      settings.jwt_secret, algorithm="HS256")


def read_state(state: str) -> dict:
    data = jwt.decode(state, settings.jwt_secret, algorithms=["HS256"], options={"verify_exp": False})
    if data["exp"] < now().timestamp():
        raise jwt.ExpiredSignatureError("state expired")
    return data


# ---- OAuth token encryption (AES-256-GCM). Only the connections service calls decrypt.
def encrypt_token(plain: str | None) -> str | None:
    if plain is None:
        return None
    nonce = os.urandom(12)
    ct = AESGCM(settings.token_enc_key).encrypt(nonce, plain.encode(), b"flu-oauth")
    return base64.b64encode(nonce + ct).decode()


def decrypt_token(enc: str | None) -> str | None:
    if enc is None:
        return None
    raw = base64.b64decode(enc)
    return AESGCM(settings.token_enc_key).decrypt(raw[:12], raw[12:], b"flu-oauth").decode()


# ---- PAN: SHA-256 with per-record salt + pepper; raw PAN never stored
def hash_pan(pan: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.sha256(f"{settings.pan_pepper}:{salt}:{pan.upper()}".encode()).hexdigest()
    return digest, salt


def hash_otp(phone: str, code: str) -> str:
    return hashlib.sha256(f"{settings.jwt_secret}:{phone}:{code}".encode()).hexdigest()


# ---- HMAC signatures (Razorpay checkout + webhooks)
def hmac_sha256(secret: str, message: str) -> str:
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def verify_hmac(secret: str, message: str, signature: str) -> bool:
    return hmac.compare_digest(hmac_sha256(secret, message), signature or "")
