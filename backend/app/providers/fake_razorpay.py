"""Simulated Razorpay: Orders, Checkout signature, Route transfers (on_hold escrow), reversals,
Linked Accounts and webhooks. Signatures use the same HMAC scheme as the real API so the
verification code path is identical in live mode."""
import json
import secrets

from sqlalchemy.orm import Session

from ..clock import now
from ..config import settings
from ..models import FakeRzpObject
from ..security import hmac_sha256


def _rid(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(7)}"


class FakeRazorpay:
    def __init__(self, db: Session):
        self.db = db

    def _put(self, kind: str, obj: dict) -> dict:
        self.db.add(FakeRzpObject(id=obj["id"], kind=kind, data=obj))
        self.db.flush()
        return obj

    def _get(self, oid: str) -> dict:
        row = self.db.get(FakeRzpObject, oid)
        if not row:
            raise KeyError(oid)
        return dict(row.data)

    def _save(self, obj: dict):
        row = self.db.get(FakeRzpObject, obj["id"])
        row.data = obj

    # POST /v1/orders
    def create_order(self, amount: int, receipt: str, notes: dict) -> dict:
        return self._put("order", {"id": _rid("order"), "entity": "order", "amount": amount, "currency": "INR",
                                   "receipt": receipt, "notes": notes, "status": "created",
                                   "created_at": int(now().timestamp())})

    # What Checkout.js returns to the browser after a successful UPI/card payment.
    def simulate_checkout(self, order_id: str, method: str = "upi") -> dict:
        order = self._get(order_id)
        pay = self._put("payment", {"id": _rid("pay"), "entity": "payment", "amount": order["amount"],
                                    "currency": "INR", "order_id": order_id, "method": method,
                                    "status": "captured", "notes": order["notes"],
                                    "created_at": int(now().timestamp())})
        order["status"] = "paid"
        self._save(order)
        sig = hmac_sha256(settings.razorpay_key_secret, f"{order_id}|{pay['id']}")
        return {"razorpay_order_id": order_id, "razorpay_payment_id": pay["id"], "razorpay_signature": sig}

    def webhook_for(self, event: str, entity_kind: str, entity: dict) -> tuple[str, str]:
        body = json.dumps({"entity": "event", "event": event, "id": _rid("evt"),
                           "payload": {entity_kind: {"entity": entity}}, "created_at": int(now().timestamp())},
                          separators=(",", ":"))
        return body, hmac_sha256(settings.razorpay_webhook_secret, body)

    def get_payment(self, payment_id: str) -> dict:
        return self._get(payment_id)

    # Route: POST /v1/accounts (+ stakeholders, products)
    def create_linked_account(self, name: str, email: str | None, bank_tail: str | None) -> dict:
        return self._put("account", {"id": _rid("acc"), "entity": "account", "legal_business_name": name,
                                     "email": email, "status": "activated", "bank_tail": bank_tail})

    # POST /v1/payments/{id}/transfers
    def create_transfer(self, payment_id: str, account: str, amount: int, notes: dict, on_hold: bool = True) -> dict:
        self._get(payment_id)
        return self._put("transfer", {"id": _rid("trf"), "entity": "transfer", "source": payment_id,
                                      "recipient": account, "amount": amount, "currency": "INR",
                                      "on_hold": on_hold, "notes": notes, "amount_reversed": 0,
                                      "settlement_status": "on_hold" if on_hold else "pending",
                                      "created_at": int(now().timestamp())})

    # PATCH /v1/transfers/{id} {on_hold:false}
    def release_transfer(self, transfer_id: str) -> dict:
        t = self._get(transfer_id)
        t["on_hold"] = False
        t["settlement_status"] = "pending"
        self._save(t)
        return t

    # POST /v1/transfers/{id}/reversals
    def reverse_transfer(self, transfer_id: str, amount: int) -> dict:
        t = self._get(transfer_id)
        t["amount_reversed"] = t.get("amount_reversed", 0) + amount
        self._save(t)
        return self._put("reversal", {"id": _rid("rvrsl"), "entity": "reversal", "transfer_id": transfer_id,
                                      "amount": amount})

    # A creator's payout from a released transfer: settles T+1..T+3, then has a UTR.
    def create_settlement(self, account: str, amount: int, notes: dict) -> dict:
        return self._put("settlement", {"id": _rid("setl"), "entity": "settlement", "recipient": account,
                                        "amount": amount, "status": "processing", "notes": notes, "utr": None})

    def settle(self, settlement_id: str) -> dict:
        s = self._get(settlement_id)
        s["status"] = "processed"
        s["utr"] = "UTR" + secrets.token_hex(6).upper()
        self._save(s)
        return s

    # GET /v1/transfers (reconciliation)
    def list(self, kind: str) -> list[dict]:
        return [r.data for r in self.db.query(FakeRzpObject).filter_by(kind=kind).all()]
