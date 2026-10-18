"""A small in-memory Razorpay behind httpx.MockTransport: enough of Orders, Route transfers, reversals and linked
account settlements to drive the live adapter and money.py's live path without the network."""
import base64
import json
import secrets
from urllib.parse import parse_qs

import httpx


class RazorpayMock:
    def __init__(self, key_id: str, key_secret: str):
        self.auth = "Basic " + base64.b64encode(f"{key_id}:{key_secret}".encode()).decode()
        self.transfers: dict[str, dict] = {}
        self.settlements: dict[str, dict] = {}
        self.calls: list[tuple[str, str, dict | None]] = []
        self.reversed_after_release = False  # pulling money back from a creator who may already be paid
        self.fail_transfers = False  # e.g. the linked account's Route product isn't activated yet

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, req: httpx.Request) -> httpx.Response:
        if req.headers.get("authorization") != self.auth:
            return httpx.Response(401, json={"error": {"code": "BAD_REQUEST_ERROR", "description": "Authentication failed"}})
        body = json.loads(req.content) if req.content else None
        path, q = req.url.path, parse_qs(req.url.query.decode())
        self.calls.append((req.method, path, body))
        parts = path.strip("/").split("/")
        if req.method == "POST" and parts[:2] == ["v1", "payments"] and parts[3:] == ["transfers"]:
            if self.fail_transfers:
                return _bad("Linked account is not activated", 400)
            items = []
            for spec in body["transfers"]:
                t = {"id": "trf_" + secrets.token_hex(7), "entity": "transfer", "status": "processed",
                     "source": parts[2], "recipient": spec["account"], "amount": spec["amount"], "currency": "INR",
                     "amount_reversed": 0, "notes": spec.get("notes") or {}, "on_hold": spec.get("on_hold", False),
                     "on_hold_until": None, "recipient_settlement_id": None,
                     "settlement_status": "on_hold" if spec.get("on_hold") else "pending", "error": {}}
                self.transfers[t["id"]] = t
                items.append(t)
            return httpx.Response(200, json={"entity": "collection", "count": len(items), "items": items})
        if parts[:2] == ["v1", "transfers"] and len(parts) >= 3:
            t = self.transfers.get(parts[2])
            if not t:
                return _bad("The id provided does not exist", 400)
            if req.method == "PATCH":
                t["on_hold"] = body["on_hold"]
                t["settlement_status"] = "on_hold" if t["on_hold"] else "pending"
                return httpx.Response(200, json=t)
            if req.method == "POST" and parts[3:] == ["reversals"]:
                if body["amount"] > t["amount"] - t["amount_reversed"]:
                    return _bad("The reversal amount exceeds the transfer amount", 400)
                if not t["on_hold"]:
                    self.reversed_after_release = True
                t["amount_reversed"] += body["amount"]
                t["status"] = "reversed" if t["amount_reversed"] == t["amount"] else "partially_reversed"
                return httpx.Response(200, json={"id": "rvrsl_" + secrets.token_hex(7), "entity": "reversal",
                                                 "transfer_id": t["id"], "amount": body["amount"], "currency": "INR"})
            if req.method == "GET":
                return httpx.Response(200, json=t)
        if req.method == "GET" and path == "/v1/transfers":
            rows = list(self.transfers.values())
            if "recipient_settlement_id" in q:
                rows = [t for t in rows if t["recipient_settlement_id"] == q["recipient_settlement_id"][0]]
            skip, count = int(q.get("skip", ["0"])[0]), int(q.get("count", ["10"])[0])
            page = rows[skip:skip + count]
            if "recipient_settlement" in q.get("expand[]", []):
                page = [{**t, "recipient_settlement": self.settlements.get(t["recipient_settlement_id"])} for t in page]
            return httpx.Response(200, json={"entity": "collection", "count": len(page), "items": page})
        return _bad(f"unhandled {req.method} {path}", 404)

    # What Razorpay does on the linked account's settlement cycle: every released, unsettled transfer goes out.
    def settle(self, account: str) -> dict | None:
        due = [t for t in self.transfers.values() if t["recipient"] == account and not t["on_hold"]
               and not t["recipient_settlement_id"] and t["amount"] > t["amount_reversed"]]
        if not due:
            return None
        s = {"id": "setl_" + secrets.token_hex(7), "entity": "settlement", "status": "processed",
             "amount": sum(t["amount"] - t["amount_reversed"] for t in due), "fees": 0, "tax": 0,
             "utr": "UTR" + secrets.token_hex(6).upper()}
        self.settlements[s["id"]] = s
        for t in due:
            t["recipient_settlement_id"], t["settlement_status"] = s["id"], "settled"
        return s

    def mirror(self, rzp_transfer_id: str, amount: int, reversed_: int, on_hold: bool):
        """Seed the mock with a transfer Flu already tracks (reconciliation tests)."""
        self.transfers.setdefault(rzp_transfer_id, {
            "id": rzp_transfer_id, "entity": "transfer", "recipient": "acc_seed", "amount": amount,
            "amount_reversed": reversed_, "on_hold": on_hold, "notes": {}, "recipient_settlement_id": None})

    def released_to(self, account: str) -> int:
        return sum(t["amount"] - t["amount_reversed"] for t in self.transfers.values()
                   if t["recipient"] == account and not t["on_hold"])

    def held_for(self, account: str) -> int:
        return sum(t["amount"] - t["amount_reversed"] for t in self.transfers.values()
                   if t["recipient"] == account and t["on_hold"])


def _bad(description: str, status: int) -> httpx.Response:
    return httpx.Response(status, json={"error": {"code": "BAD_REQUEST_ERROR", "description": description,
                                                  "source": "business", "step": "payment_initiation",
                                                  "reason": "input_validation_failed", "field": "id"}})
