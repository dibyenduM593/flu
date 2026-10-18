"""Creator KYC before first payout (CR-6): PAN (hashed + last 4), bank penny-drop or UPI, Route linked account."""
from sqlalchemy.orm import Session

from .. import providers
from ..clock import now
from ..errors import ApiError
from ..models import CreatorProfile, KycRecord, Org, User
from ..providers.base import ProviderError, ProviderUnavailable
from ..security import hash_pan
from .money import release_kyc_holds
from .ops import audit, open_item

NAME_MATCH_MIN = 0.8
LINKED_ACCOUNT_ERRORS = {
    "bank_account_required": "Payouts need a bank account (IFSC + number); UPI-only payouts aren't supported yet.",
    "email_required": "Add an email address to receive payouts.",
    "address_required": "Add your address (street, city, state, PIN code) to receive payouts.",
}


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ProviderUnavailable as e:
        raise ApiError(502, "kyc_provider_unavailable", "Verification is temporarily unavailable. Try again in a few minutes.",
                       {"provider_code": e.code}) from e


def submit(db: Session, cp: CreatorProfile, pan: str, name: str, ifsc: str | None, account_number: str | None,
           vpa: str | None, gstin: str | None, email: str | None = None, address: dict | None = None) -> KycRecord:
    k = providers.kyc()
    rec = db.get(KycRecord, cp.user_id) or KycRecord(creator_id=cp.user_id)
    db.add(rec)
    pan = (pan or "").upper().strip()
    res = _call(k.verify_pan, pan, name)

    def fail(reason: str, msg: str):
        rec.status, rec.fail_reason = "failed", reason
        cp.kyc_status = "failed"
        open_item(db, "kyc_fail", reason, "creator", cp.user_id, f"KYC failed for {cp.display_name}: {reason}",
                  {"pan_last4": pan[-4:] if pan else None})
        db.commit()
        raise ApiError(422, reason, msg)

    if not res["valid"]:
        fail(res["reason"], "That PAN doesn't look right. Check the 10 characters on your card.")
    if res["name_match"] < NAME_MATCH_MIN:
        fail("pan_name_mismatch", "The name doesn't match the PAN records. Use the name exactly as on your PAN.")
    bank = _call(k.penny_drop, ifsc, account_number, vpa, name)
    if not bank["valid"]:
        fail(bank["reason"], "We couldn't verify that bank account or UPI ID.")
    if bank.get("name_match", 1.0) < NAME_MATCH_MIN:
        fail("bank_name_mismatch", "The name on that bank account or UPI ID doesn't match your PAN name.")
    digest, salt = hash_pan(pan)
    rec.pan_hash, rec.pan_salt, rec.pan_last4, rec.pan_name = digest, salt, pan[-4:], name
    rec.name_match, rec.bank_verified = res["name_match"], True
    rec.ifsc = ifsc.upper() if ifsc else None
    rec.account_tail = account_number[-4:] if account_number else None
    rec.vpa = vpa
    rec.gstin = gstin or None
    rec.fund_account_id, rec.provider_ref = bank["ref"], res["ref"]
    if not rec.linked_account_id:
        user = db.get(User, cp.user_id)
        if email:
            user.email = email
        try:
            acc = _call(providers.razorpay(db).create_linked_account, name, user.email, rec.account_tail,
                        phone=user.phone, pan=pan, ifsc=rec.ifsc, account_number=account_number, reference_id=cp.user_id,
                        address=address)
        except ProviderError as e:
            open_item(db, "kyc_fail", e.code, "creator", cp.user_id, f"Route linked account setup failed for {cp.display_name}",
                      {"provider_message": str(e)[:300]})
            fail(e.code, LINKED_ACCOUNT_ERRORS.get(e.code, "We couldn't set up payouts to that account."))
        rec.linked_account_id = acc["id"]
    rec.status, rec.fail_reason, rec.verified_at = "verified", None, now()
    cp.kyc_status = "verified"
    # Collusion control: same PAN on a brand workspace and a creator profile.
    for org in db.query(Org).filter(Org.pan.isnot(None)).all():
        if hash_pan(org.pan, salt)[0] == digest:
            open_item(db, "fraud_flag", "same_pan_brand_creator", "creator", cp.user_id,
                      f"{cp.display_name} shares a PAN with brand {org.name}", {"org_id": org.id})
    audit(db, cp.user_id, "kyc.verified", "creator", cp.user_id, None, {"pan_last4": rec.pan_last4})
    db.flush()
    release_kyc_holds(db, cp.user_id)
    db.commit()
    return rec


def public(rec: KycRecord | None) -> dict:
    if not rec:
        return {"status": "none"}
    return {"status": rec.status, "pan_last4": rec.pan_last4, "pan_name": rec.pan_name, "bank_verified": rec.bank_verified,
            "account_tail": rec.account_tail, "ifsc": rec.ifsc, "vpa": rec.vpa, "gstin": rec.gstin,
            "fail_reason": rec.fail_reason, "verified_at": rec.verified_at}
