"""Simulated PAN verification + bank penny-drop (Cashfree / Razorpay fund-account validation shapes).

Test conventions: a PAN whose first five letters are ZZZZZ returns a different registered name
(name-match failure); an account number ending 0000 fails penny-drop."""
import re
import secrets
from difflib import SequenceMatcher

PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
VPA_RE = re.compile(r"^[\w.\-]{2,}@[a-z]{2,}$")


def name_score(a: str, b: str) -> float:
    norm = lambda s: " ".join(sorted(s.lower().replace(".", " ").split()))
    return round(SequenceMatcher(None, norm(a), norm(b)).ratio(), 2)


class FakeKyc:
    def verify_pan(self, pan: str, name: str) -> dict:
        pan = pan.upper().strip()
        if not PAN_RE.match(pan):
            return {"valid": False, "reason": "invalid_pan_format"}
        registered = "Registered Holder" if pan.startswith("ZZZZZ") else name
        return {"valid": True, "registered_name": registered, "name_match": name_score(name, registered),
                "ref": "pan_" + secrets.token_hex(5)}

    def penny_drop(self, ifsc: str | None, account_number: str | None, vpa: str | None, name: str) -> dict:
        if vpa:
            if not VPA_RE.match(vpa):
                return {"valid": False, "reason": "invalid_vpa"}
            return {"valid": True, "registered_name": name, "name_match": 1.0, "ref": "fav_" + secrets.token_hex(5)}
        if not ifsc or not IFSC_RE.match(ifsc.upper()):
            return {"valid": False, "reason": "invalid_ifsc"}
        if not account_number or not account_number.isdigit() or not 9 <= len(account_number) <= 18:
            return {"valid": False, "reason": "invalid_account_number"}
        if account_number.endswith("0000"):
            return {"valid": False, "reason": "penny_drop_failed"}
        return {"valid": True, "registered_name": name, "name_match": 1.0, "ref": "fav_" + secrets.token_hex(5)}
