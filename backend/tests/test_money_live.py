"""Live Route escrow: money.py with RazorpayLive against an in-memory Razorpay (no network).

The creator is never paid more than the ledger's net, escrow slices release as batches are finalized, closing a
hire pays the exact remainder and reverses the rest, and settlement webhooks (or the settle_payouts poll) mark
batches paid. Fake mode ignores the Route events."""
import json
import secrets
from datetime import timedelta

import pytest

from app import providers
from app.clock import now
from app.config import settings
from app.models import Brief, Deliverable, Hire, KycRecord, OpsItem, Org, Payment, Payout, Transfer, WebhookEvent
from app.providers.razorpay_live import RazorpayLive
from app.security import hmac_sha256
from app.services import money
from razorpay_mock import RazorpayMock


@pytest.fixture
def rzp(monkeypatch):
    mock = RazorpayMock(settings.razorpay_key_id, settings.razorpay_key_secret)
    monkeypatch.setattr(providers, "razorpay", lambda db: RazorpayLive(transport=mock.transport))
    return mock


def _webhook(db, event: str, kind: str, entity: dict) -> dict:
    raw = json.dumps({"entity": "event", "account_id": "acc_flu", "event": event, "contains": [kind],
                      "payload": {kind: {"entity": entity}}, "created_at": int(now().timestamp())})
    return money.handle_webhook(db, raw, hmac_sha256(settings.razorpay_webhook_secret, raw), "evt_" + secrets.token_hex(8))


def _fresh_hire(db):
    """A new hire for a KYC-verified seeded creator (seeded rows supply the foreign keys), with its own top-up."""
    for h in db.query(Hire).all():
        kyc = db.get(KycRecord, h.creator_id)
        d = db.query(Deliverable).filter_by(hire_id=h.id).first()
        if kyc and kyc.status == "verified" and kyc.linked_account_id and d:
            break
    else:
        pytest.skip("seed has no KYC-verified creator with a deliverable")
    brief = db.get(Brief, h.brief_id)
    org = db.get(Org, brief.org_id)
    reserve = money.reserve_for(brief, org)
    pay = Payment(org_id=org.id, rzp_order_id="order_" + secrets.token_hex(7), rzp_payment_id="pay_" + secrets.token_hex(7),
                  amount_paise=reserve, status="captured", captured_at=now())
    db.add(pay)
    db.flush()
    money.post(db, org.id, "topup", reserve, "payment", pay.id, f"topup:{pay.rzp_payment_id}", "Wallet top-up")
    hire = Hire(brief_id=brief.id, creator_id=h.creator_id, application_id=h.application_id, reserved_paise=reserve)
    db.add(hire)
    db.flush()
    dl = Deliverable(hire_id=hire.id, media_item_id=d.media_item_id, post_url=d.post_url, status="approved",
                     approved_at=now(), approval_deadline_at=now(), tracking_status="ended", tracking_ends_at=now())
    db.add(dl)
    db.flush()
    return hire, dl, brief, org, kyc.linked_account_id


def test_escrow_slices():
    assert money.escrow_slices(50) == []  # below Razorpay's ₹1 minimum transfer
    assert money.escrow_slices(25_000) == [10_000, 10_000, 5_000]  # ₹100 minimum slice
    assert money.escrow_slices(20_050) == [10_000, 10_050]  # a sub-₹1 tail joins the last slice
    parts = money.escrow_slices(10_000_00)
    assert sum(parts) == 10_000_00 and len(parts) == settings.razorpay_escrow_max_slices
    assert sum(money.escrow_slices(10_000_37)) == 10_000_37


def test_live_escrow_never_overpays_and_settles_from_webhooks(db, rzp):
    hire, dl, brief, org, acct = _fresh_hire(db)
    money.reserve_hire(db, hire, org, None)
    escrow = money.per_deliverable_cap(brief) * brief.deliverables_per_creator
    ts = db.query(Transfer).filter_by(hire_id=hire.id).all()
    assert sum(t.amount_paise for t in ts) == escrow == rzp.held_for(acct)
    assert len(ts) > 1 and all(t.on_hold for t in ts)
    slice_max = max(t.amount_paise for t in ts)

    def batch(gross: int) -> Payout:
        p = Payout(creator_id=hire.creator_id, deliverable_id=dl.id, org_id=org.id, amount_paise=gross,
                   net_paise=gross, status="queued")
        db.add(p)
        db.flush()
        money.finalize(db, p)
        owed = money.owed_net(db, hire)
        assert p.status == "processing" and p.net_paise == gross - p.fee_paise - p.tds_paise
        assert owed - slice_max < rzp.released_to(acct) <= owed  # whole slices, never ahead of the ledger
        return p

    p1 = batch(escrow // 4 + 37)  # odd amounts so batches never line up with slice boundaries
    db.commit()
    s1 = rzp.settle(acct)
    assert _webhook(db, "settlement.processed", "settlement", s1)["status"] == "processed"
    assert rzp.released_to(acct) < p1.net_paise and p1.status == "processing"  # paid in part, not yet complete

    p2 = batch(escrow // 5 + 11)
    assert p1.rzp_transfer_id  # the second batch released the slice that completes the first
    db.commit()
    s2 = rzp.settle(acct)
    _webhook(db, "settlement.processed", "settlement", s2)
    assert p1.status == "processed" and p1.utr in (s1["utr"], s2["utr"])

    money.close_hire_if_done(db, hire, force=True)
    db.commit()
    owed = money.owed_net(db, hire)
    assert hire.status == "completed"
    assert rzp.held_for(acct) == 0 and rzp.released_to(acct) == owed  # exact, after trimming the last slice
    assert sum(t.reversed_paise for t in ts) == escrow - owed  # fee, TDS and unspent reserve came back to Flu
    assert not rzp.reversed_after_release

    s3 = rzp.settle(acct)
    last = db.query(Payout).filter_by(deliverable_id=dl.id).order_by(Payout.created_at.desc()).first()
    t_last = rzp.transfers[last.rzp_transfer_id]
    _webhook(db, "transfer.processed", "transfer", t_last)
    assert last.status == "processed" and last.utr == s3["utr"]
    for p in db.query(Payout).filter_by(deliverable_id=dl.id, status="processing").all():
        p.settle_after = now() - timedelta(hours=1)  # the poll catches any batch whose webhook never came
    money.settle_payouts(db)
    assert {p.status for p in db.query(Payout).filter_by(deliverable_id=dl.id).all()} == {"processed"}

    # Reconciliation compares every tracked transfer with Razorpay's view of it.
    for t in db.query(Transfer).all():
        rzp.mirror(t.rzp_transfer_id, t.amount_paise, t.reversed_paise, t.on_hold)
    assert money.reconcile(db)["issues"] == 0
    rzp.transfers[ts[0].rzp_transfer_id]["amount_reversed"] += 100
    rzp.mirror("trf_untracked", 5_000, 0, True)
    assert money.reconcile(db)["issues"] == 2  # the tampered transfer and the untracked one
    item = db.query(OpsItem).filter_by(type="reconcile", reason_code="ledger_mismatch", status="open").first()
    assert {i.get("rzp_transfer_id") for i in item.details["issues"]} >= {ts[0].rzp_transfer_id, "trf_untracked"}
    item.status = "resolved"
    db.commit()


def test_transfer_failure_opens_ops_item_without_failing_the_hire(db, rzp):
    hire, dl, brief, org, acct = _fresh_hire(db)
    rzp.fail_transfers = True
    money.reserve_hire(db, hire, org, None)
    assert db.query(Transfer).filter_by(hire_id=hire.id).count() == 0
    assert db.query(OpsItem).filter_by(reason_code="transfer_create_failed", entity_id=hire.id).count() == 1
    rzp.fail_transfers = False
    money.close_hire_if_done(db, hire, force=True)  # nothing earned: the reserve goes back to the wallet
    db.commit()


def test_transfer_failed_webhook_opens_ops_item(db, rzp):
    _webhook(db, "transfer.failed", "transfer", {"id": "trf_failed1", "entity": "transfer", "status": "failed",
                                                 "error": {"code": "BAD_REQUEST_ERROR", "reason": "insufficient_balance"}})
    assert db.query(OpsItem).filter_by(reason_code="transfer_failed", entity_id="trf_failed1").count() == 1


def test_fake_mode_stores_route_events_and_ignores_them(db):
    before = db.query(Payout).filter_by(status="processing").count()
    out = _webhook(db, "settlement.processed", "settlement", {"id": "setl_fake", "entity": "settlement",
                                                            "amount": 100, "status": "processed", "utr": "UTR1"})
    assert out == {"status": "processed", "event": "settlement.processed"}
    assert db.query(Payout).filter_by(status="processing").count() == before
    assert db.query(WebhookEvent).filter_by(event="settlement.processed").count() >= 1


def test_webhook_dedupes_on_event_id_header(db):
    raw = json.dumps({"entity": "event", "event": "transfer.processed", "contains": ["transfer"],
                      "payload": {"transfer": {"entity": {"id": "trf_x"}}}})
    sig = hmac_sha256(settings.razorpay_webhook_secret, raw)
    assert money.handle_webhook(db, raw, sig, "evt_dupe_1")["status"] == "processed"
    assert money.handle_webhook(db, raw, sig, "evt_dupe_1") == {"status": "duplicate"}
