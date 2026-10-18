"""Razorpay (api.razorpay.com): Orders, payments, Route linked accounts, transfers held on_hold as escrow, release,
reversals and settlement lookups. Basic auth with the key id and secret.

Same method names and return shapes as FakeRazorpay, with one difference: there is no create_settlement/settle.
A released transfer settles with the linked account's next settlement; money.handle_webhook (settlement.processed,
transfer.processed) and money.settle_payouts (polling fallback) mark the payout paid from that.

The test suite runs this against httpx.MockTransport only. Re-verify request fields against Razorpay's docs and a
test-mode account before switching PROVIDER_MODE=live."""
import re

import httpx

from ..config import settings
from .base import ProviderError, ProviderUnavailable


class RazorpayLive:
    live = True

    def __init__(self, transport: httpx.BaseTransport | None = None):
        self.http = httpx.Client(base_url=settings.razorpay_base_url, transport=transport, timeout=20,
                                 auth=(settings.razorpay_key_id, settings.razorpay_key_secret))

    def _call(self, method: str, path: str, json: dict | None = None, params: dict | list | None = None) -> dict:
        try:
            r = self.http.request(method, path, json=json, params=params)
        except httpx.TransportError as e:
            raise ProviderUnavailable("razorpay_unreachable", str(e)) from e
        try:
            body = r.json() if r.content else {}
        except ValueError:
            body = {}
        err = body.get("error") if isinstance(body, dict) else None
        if r.status_code >= 500 or r.status_code in (401, 429):
            raise ProviderUnavailable((err or {}).get("code") or f"razorpay_http_{r.status_code}",
                                      (err or {}).get("description") or r.text[:200])
        if r.status_code >= 400:
            raise ProviderError((err or {}).get("code") or f"razorpay_http_{r.status_code}",
                                (err or {}).get("description") or r.text[:200])
        return body

    # POST /v1/orders
    def create_order(self, amount: int, receipt: str, notes: dict) -> dict:
        return self._call("POST", "/v1/orders", {"amount": amount, "currency": "INR", "receipt": receipt,
                                                 "notes": _notes(notes)})

    def get_payment(self, payment_id: str) -> dict:
        return self._call("GET", f"/v1/payments/{payment_id}")

    # Route linked account for an individual creator: POST /v2/accounts, then the stakeholder (an individual's PAN
    # goes on the stakeholder; legal_info.pan only accepts business PANs), then the Route product with the bank.
    def create_linked_account(self, name: str, email: str | None, bank_tail: str | None, *, phone: str | None = None,
                              pan: str | None = None, ifsc: str | None = None, account_number: str | None = None,
                              reference_id: str | None = None, address: dict | None = None) -> dict:
        if not (ifsc and account_number):
            raise ProviderError("bank_account_required", "Route settles linked accounts to a bank account only")
        if not email:
            raise ProviderError("email_required", "Route linked accounts need an email address")
        addr = {k: str((address or {}).get(k) or "").strip() for k in ("street1", "street2", "city", "state", "postal_code")}
        if not (addr["street1"] and addr["city"] and addr["state"] and addr["postal_code"]):
            raise ProviderError("address_required", "Route linked accounts need a registered address")
        phone10 = re.sub(r"\D", "", phone or "")[-10:]
        acc = self._call("POST", "/v2/accounts", {
            "email": email, "phone": phone10, "type": "route", "legal_business_name": name,
            "business_type": "individual", "contact_name": name,
            **({"reference_id": re.sub(r"[^A-Za-z0-9]", "", reference_id)[-20:]} if reference_id else {}),
            "profile": {"category": settings.razorpay_route_category,
                        "subcategory": settings.razorpay_route_subcategory,
                        "addresses": {"registered": {**addr, "street2": addr["street2"] or addr["city"], "country": "IN"}}},
        })
        try:
            self._call("POST", f"/v2/accounts/{acc['id']}/stakeholders", {
                "name": name, "email": email, **({"phone": {"primary": phone10}} if phone10 else {}),
                **({"kyc": {"pan": pan}} if pan else {}),
                "addresses": {"residential": {"street": " ".join(filter(None, (addr["street1"], addr["street2"]))),
                                              "city": addr["city"], "state": addr["state"],
                                              "postal_code": addr["postal_code"], "country": "IN"}}})
            product = self._call("POST", f"/v2/accounts/{acc['id']}/products",
                                 {"product_name": "route", "tnc_accepted": True})
            product = self._call("PATCH", f"/v2/accounts/{acc['id']}/products/{product['id']}/", {
                "settlements": {"account_number": account_number, "ifsc_code": ifsc.upper(),
                                "beneficiary_name": name},
                "tnc_accepted": True})
        except ProviderError as e:
            # The account exists without a working Route product; ops can finish it in the dashboard.
            raise type(e)(e.code, f"linked account {acc['id']} created but setup failed: {e}") from e
        # activation_status can be under_review / needs_clarification; transfers to it fail until it is activated.
        return {"id": acc["id"], "entity": "account", "legal_business_name": name, "email": email,
                "status": product.get("activation_status") or acc.get("status"), "bank_tail": bank_tail,
                "product_id": product.get("id"), "requirements": product.get("requirements") or []}

    # POST /v1/payments/{id}/transfers
    def create_transfer(self, payment_id: str, account: str, amount: int, notes: dict, on_hold: bool = True) -> dict:
        out = self._call("POST", f"/v1/payments/{payment_id}/transfers", {"transfers": [{
            "account": account, "amount": amount, "currency": "INR", "notes": _notes(notes), "on_hold": on_hold}]})
        items = out.get("items") if out.get("entity") == "collection" else [out]
        if not items:
            raise ProviderError("transfer_missing", f"no transfer returned for {payment_id}")
        return items[0]

    # PATCH /v1/transfers/{id} {on_hold:false}
    def release_transfer(self, transfer_id: str) -> dict:
        return self._call("PATCH", f"/v1/transfers/{transfer_id}", {"on_hold": False})

    # POST /v1/transfers/{id}/reversals
    def reverse_transfer(self, transfer_id: str, amount: int) -> dict:
        return self._call("POST", f"/v1/transfers/{transfer_id}/reversals", {"amount": amount})

    def get_transfer(self, transfer_id: str) -> dict:
        return self._call("GET", f"/v1/transfers/{transfer_id}")

    # The linked account settlement (with its UTR) that paid a released transfer out, once there is one.
    # expand[]=recipient_settlement is documented on the list call, so read it off any transfer in that settlement.
    def transfer_settlement(self, transfer_id: str) -> dict | None:
        sid = self.get_transfer(transfer_id).get("recipient_settlement_id")
        if not sid:
            return None
        items = self._call("GET", "/v1/transfers", params=[("recipient_settlement_id", sid), ("count", 1),
                                                           ("expand[]", "recipient_settlement")]).get("items") or []
        s = items[0].get("recipient_settlement") if items else None
        return s if isinstance(s, dict) and s.get("status") == "processed" else None

    # GET /v1/transfers?recipient_settlement_id=: the transfers a linked account settlement paid out.
    def settlement_transfers(self, settlement_id: str) -> list[dict]:
        return self._pages("/v1/transfers", {"recipient_settlement_id": settlement_id})

    def _pages(self, path: str, params: dict, count: int = 100) -> list[dict]:
        out, skip = [], 0
        while True:
            page = self._call("GET", path, params={**params, "count": count, "skip": skip}).get("items") or []
            out += page
            if len(page) < count:
                return out
            skip += count

    # GET /v1/{kind}s (reconciliation). Defined last: the name shadows the builtin in the class body.
    def list(self, kind: str) -> list[dict]:
        return self._pages(f"/v1/{kind}s", {})


def _notes(notes: dict) -> dict:
    """Razorpay notes: at most 15 string values of up to 256 characters."""
    return {str(k): str(v)[:256] for k, v in list((notes or {}).items())[:15]}
