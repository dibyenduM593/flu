"""Cashfree Verification Suite (Secure ID): PAN, bank account (penny drop, sync) and UPI ID.

Same return shapes as FakeKyc: {"valid", "registered_name", "name_match" (0..1), "ref"} or {"valid": False, "reason"}.
Cashfree scores names 0-100; this adapter scales to 0-1 so kyc.submit's 0.8 threshold applies, and falls back to
Flu's own name_score when a score isn't returned (UPI, or name match not enabled on the account).

The test suite runs this against httpx.MockTransport only."""
import base64
import time

import httpx

from ..config import settings
from .base import ProviderError, ProviderUnavailable
from .fake_kyc import IFSC_RE, PAN_RE, VPA_RE, name_score

BANK_FAIL_REASONS = {"INVALID_IFSC_FAIL": "invalid_ifsc", "INVALID_ACCOUNT_FAIL": "penny_drop_failed",
                     "ACCOUNT_BLOCKED": "account_blocked", "NRE_ACCOUNT_FAIL": "nre_account"}


class CashfreeKyc:
    def __init__(self, transport: httpx.BaseTransport | None = None):
        self.http = httpx.Client(base_url=settings.cashfree_base_url.rstrip("/") + "/", transport=transport, timeout=30)

    def _headers(self) -> dict:
        h = {"x-client-id": settings.cashfree_client_id, "x-client-secret": settings.cashfree_client_secret}
        if settings.cashfree_public_key:
            h["x-cf-signature"] = _signature(settings.cashfree_client_id, settings.cashfree_public_key)
        return h

    def _post(self, path: str, body: dict) -> tuple[int, dict]:
        try:
            r = self.http.post(path, json=body, headers=self._headers())
        except httpx.TransportError as e:
            raise ProviderUnavailable("cashfree_unreachable", str(e)) from e
        try:
            data = r.json()
        except ValueError:
            data = {}
        # 401/403: credentials, IP whitelist or signature; 422 insufficient_balance; 429; 5xx. None is the user's fault.
        if r.status_code in (401, 403, 422, 429) or r.status_code >= 500:
            raise ProviderUnavailable(data.get("code") or f"cashfree_http_{r.status_code}",
                                      data.get("message") or r.text[:200])
        if r.status_code >= 400 and data.get("type") != "validation_error":
            raise ProviderError(data.get("code") or f"cashfree_http_{r.status_code}", data.get("message") or r.text[:200])
        return r.status_code, data

    # POST /verification/pan
    def verify_pan(self, pan: str, name: str) -> dict:
        pan = pan.upper().strip()
        if not PAN_RE.match(pan):
            return {"valid": False, "reason": "invalid_pan_format"}
        status, d = self._post("pan", {"pan": pan, "name": name})
        if status >= 400:
            return {"valid": False, "reason": "invalid_pan_format"}
        if not d.get("valid") or (d.get("pan_status") or "VALID") != "VALID":
            return {"valid": False, "reason": "pan_" + str(d.get("pan_status") or "invalid").lower()}
        registered = d.get("registered_name") or d.get("name_pan_card") or ""
        return {"valid": True, "registered_name": registered, "name_match": _score(d, name, registered),
                "ref": f"cf_pan_{d.get('reference_id')}"}

    def penny_drop(self, ifsc: str | None, account_number: str | None, vpa: str | None, name: str) -> dict:
        if vpa:
            return self._verify_upi(vpa, name)
        if not ifsc or not IFSC_RE.match(ifsc.upper()):
            return {"valid": False, "reason": "invalid_ifsc"}
        if not account_number or not account_number.isdigit() or not 9 <= len(account_number) <= 18:
            return {"valid": False, "reason": "invalid_account_number"}
        # POST /verification/bank-account/sync: a ₹1 penny drop that returns the beneficiary name at the bank.
        status, d = self._post("bank-account/sync", {"bank_account": account_number, "ifsc": ifsc.upper(), "name": name})
        if status >= 400:
            return {"valid": False, "reason": "invalid_account_number"}
        if d.get("account_status") != "VALID":
            return {"valid": False, "reason": BANK_FAIL_REASONS.get(d.get("account_status_code"), "penny_drop_failed")}
        at_bank = d.get("name_at_bank") or ""
        return {"valid": True, "registered_name": at_bank, "name_match": _score(d, name, at_bank),
                "ref": f"cf_bav_{d.get('reference_id')}"}

    # POST /verification/upi: NPCI name lookup on the VPA, no score in the response.
    def _verify_upi(self, vpa: str, name: str) -> dict:
        if not VPA_RE.match(vpa):
            return {"valid": False, "reason": "invalid_vpa"}
        vid = f"flu{int(time.time() * 1000)}"
        status, d = self._post("upi", {"verification_id": vid, "vpa": vpa, "name": name})
        if status >= 400 or d.get("status") != "VALID":
            return {"valid": False, "reason": "invalid_vpa"}
        at_bank = d.get("name_at_bank") or ""
        return {"valid": True, "registered_name": at_bank, "name_match": _score(d, name, at_bank),
                "ref": f"cf_upi_{d.get('reference_id') or vid}"}


def _score(d: dict, provided: str, registered: str) -> float:
    raw = d.get("name_match_score")
    if raw not in (None, ""):
        try:
            return round(float(str(raw)) / 100, 2)
        except ValueError:
            pass
    return name_score(provided, registered) if registered else 0.0


def _signature(client_id: str, public_key_pem: str) -> str:
    """x-cf-signature: RSA-OAEP (SHA-1) of "{client_id}.{unix_ts}" with the dashboard public key; valid ~5 minutes."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    pem = public_key_pem
    if not pem.lstrip().startswith("-----BEGIN"):
        with open(pem, "rb") as f:  # a path to the .pem file
            pem = f.read().decode()
    key = serialization.load_pem_public_key(pem.encode())
    ct = key.encrypt(f"{client_id}.{int(time.time())}".encode(),
                     padding.OAEP(mgf=padding.MGF1(hashes.SHA1()), algorithm=hashes.SHA1(), label=None))
    return base64.b64encode(ct).decode()
