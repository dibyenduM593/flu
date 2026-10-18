"""Wallet, escrow, payouts, TDS and invoices (PRD § Payments, escrow and Indian compliance).

The ledger is append-only and every balance is derived. Signs per kind:

  topup +X            brand payment captured (webhook)
  reserve -R          on hire: cap x deliverables + GST on the maximum platform fee
  release_reserve +r  moves money out of reserve, either to pay a batch or back to available
  payout -net         creator's share of a released batch (gross - fee - TDS)
  fee -F              Flu's take rate on the batch
  fee_gst -G          18% GST on Flu's fee, invoiced to the brand
  tds_withheld -T     Section 194-O TDS deposited by Flu
  refund -X           unused top-up returned

available = sum(all entries); reserved = -(reserve + release_reserve); spent = payout + fee + fee_gst + tds.
A release of gross P posts release_reserve +(P+G) and payout/fee/fee_gst/tds summing to -(P+G), so a
release never changes `available`; only the final close of a hire returns unspent reserve.
"""
import csv
import hashlib
import io
import json
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import providers
from ..clock import now
from ..config import (GST_RATE, GST_REQUIRED_TOPUP_PAISE, MIN_TOPUP_PAISE, TAKE_RATE, TDS_194O_EXEMPT_PAISE,
                      TDS_194O_RATE, TDS_NO_PAN_RATE, settings)
from ..errors import ApiError, bad, conflict, not_found
from ..models import (Brief, CreatorProfile, Deliverable, Hire, KycRecord, LedgerEntry, Org, OrgMember, Payment, Payout,
                      Transfer, ViewLedger, Wallet, WebhookEvent)
from ..providers.base import ProviderError
from ..security import verify_hmac
from . import jobs
from .ops import audit, notify, open_item
from .audit import IST

RZP_MIN_TRANSFER_PAISE = 100
SIGNS = {"topup": 1, "reserve": -1, "release_reserve": 1, "payout": -1, "fee": -1, "fee_gst": -1,
         "tds_withheld": -1, "refund": -1}


# ------------------------------------------------------------------ ledger primitives
def wallet(db: Session, org_id: str) -> Wallet:
    w = db.get(Wallet, org_id)
    if not w:
        w = Wallet(org_id=org_id)
        db.add(w)
        db.flush()
    return w


def post(db: Session, org_id: str, kind: str, amount: int, ref_type: str, ref_id: str, key: str,
         memo: str | None = None, actor: str | None = None) -> LedgerEntry:
    """Idempotent on `key`; amounts are integer paise with the kind's sign enforced."""
    existing = db.query(LedgerEntry).filter_by(idempotency_key=key).first()
    if existing:
        return existing
    amount = int(amount)
    if kind in SIGNS and amount * SIGNS[kind] < 0:
        raise ValueError(f"{kind} must have sign {SIGNS[kind]}, got {amount}")
    wallet(db, org_id)
    e = LedgerEntry(wallet_id=org_id, kind=kind, amount_paise=amount, ref_type=ref_type, ref_id=ref_id,
                    memo=memo, created_by=actor, idempotency_key=key)
    db.add(e)
    db.flush()
    audit(db, actor, f"ledger.{kind}", ref_type, ref_id, None, {"amount_paise": amount, "key": key})
    return e


def summary(db: Session, org_id: str) -> dict:
    rows = dict(db.query(LedgerEntry.kind, func.sum(LedgerEntry.amount_paise))
                .filter(LedgerEntry.wallet_id == org_id).group_by(LedgerEntry.kind).all())
    g = lambda k: int(rows.get(k) or 0)
    return {
        "available_paise": sum(int(v or 0) for v in rows.values()),
        "reserved_paise": -(g("reserve") + g("release_reserve")),
        "spent_paise": -(g("payout") + g("fee") + g("fee_gst") + g("tds_withheld")),
        "paid_to_creators_paise": -g("payout"), "fees_paise": -g("fee"), "fee_gst_paise": -g("fee_gst"),
        "tds_paise": -g("tds_withheld"), "topped_up_paise": g("topup"), "refunded_paise": -g("refund"),
        "currency": "INR",
    }


def available(db: Session, org_id: str) -> int:
    return int(db.query(func.coalesce(func.sum(LedgerEntry.amount_paise), 0))
               .filter(LedgerEntry.wallet_id == org_id).scalar())


def take_rate(org: Org) -> float:
    return TAKE_RATE.get(org.plan, 0.15)


def per_deliverable_cap(brief: Brief) -> int:
    if brief.pay_model == "flat":
        return brief.flat_paise
    return max(brief.cap_paise, brief.flat_paise)


def reserve_for(brief: Brief, org: Org) -> int:
    """Per-creator reserve: max payout for all their deliverables + GST on the max platform fee."""
    gross = per_deliverable_cap(brief) * brief.deliverables_per_creator
    return gross + round(round(gross * take_rate(org)) * GST_RATE)


# ------------------------------------------------------------------ top-ups (Razorpay Orders + webhook)
def create_topup(db: Session, org: Org, amount_paise: int, actor: str) -> dict:
    if not isinstance(amount_paise, int) or amount_paise < MIN_TOPUP_PAISE:
        raise bad("topup_too_small", "minimum top-up is ₹5,000", min_paise=MIN_TOPUP_PAISE)
    if amount_paise > GST_REQUIRED_TOPUP_PAISE and not org.gstin:
        raise bad("gstin_required", "add your GSTIN before a top-up above ₹50,000")
    rzp = providers.razorpay(db)
    order = rzp.create_order(amount_paise, receipt=f"topup_{org.id[:8]}", notes={"org_id": org.id})
    db.add(Payment(org_id=org.id, rzp_order_id=order["id"], amount_paise=amount_paise))
    audit(db, actor, "wallet.topup_order", "org", org.id, None, {"order_id": order["id"], "amount": amount_paise})
    db.commit()
    return {"order_id": order["id"], "amount_paise": amount_paise, "currency": "INR", "key_id": settings.razorpay_key_id,
            "checkout_url": f"{settings.web_origin}/dev/checkout?order_id={order['id']}" if settings.provider_mode == "fake" else None}


def verify_checkout(db: Session, order_id: str, payment_id: str, signature: str) -> bool:
    """HMAC_SHA256(order_id + "|" + payment_id, key_secret). The wallet is credited by the webhook, not here."""
    ok = verify_hmac(settings.razorpay_key_secret, f"{order_id}|{payment_id}", signature)
    if not ok:
        raise bad("signature_invalid", "payment signature did not verify")
    p = db.query(Payment).filter_by(rzp_order_id=order_id).first()
    if p and not p.rzp_payment_id:
        p.rzp_payment_id = payment_id
        db.commit()
    return ok


def handle_webhook(db: Session, raw_body: str, signature: str | None, event_id: str | None = None) -> dict:
    """`event_id` is the X-Razorpay-Event-Id header; live payloads carry no id of their own."""
    verified = verify_hmac(settings.razorpay_webhook_secret, raw_body, signature or "")
    data = json.loads(raw_body)
    evt_id = event_id or data.get("id") or "noid_" + hashlib.sha256(raw_body.encode()).hexdigest()[:40]
    if db.get(WebhookEvent, evt_id):
        return {"status": "duplicate"}
    db.add(WebhookEvent(id=evt_id, provider="razorpay", event=data.get("event", "?"), payload=data, verified=verified))
    if not verified:
        open_item(db, "reconcile", "webhook_signature_failed", "webhook", evt_id,
                  "Razorpay webhook failed signature verification (quarantined)", {"event": data.get("event")})
        db.commit()
        raise ApiError(400, "signature_invalid", "webhook signature invalid; stored in quarantine")
    event = data["event"]
    if event == "payment.captured":
        pay = data["payload"]["payment"]["entity"]
        p = db.query(Payment).filter_by(rzp_order_id=pay["order_id"]).first()
        if p and p.status != "captured":
            p.status, p.rzp_payment_id, p.captured_at = "captured", pay["id"], now()
            post(db, p.org_id, "topup", pay["amount"], "payment", p.id, f"topup:{pay['id']}", "Wallet top-up")
            for m in db.query(OrgMember).filter_by(org_id=p.org_id).all():
                notify(db, m.user_id, "wallet_credited", f"₹{pay['amount'] / 100:,.0f} added to your wallet.", "/brand/wallet")
    elif event == "payment.failed":
        pay = data["payload"]["payment"]["entity"]
        p = db.query(Payment).filter_by(rzp_order_id=pay["order_id"]).first()
        if p:
            p.status = "failed"
    elif event.startswith(("transfer.", "settlement.")):
        _route_event(db, event, data["payload"])
    db.commit()
    return {"status": "processed", "event": event}


def _route_event(db: Session, event: str, payload: dict):
    """Live Route: a released transfer settles to the creator's bank with the linked account's next settlement.
    The simulator never sends these; it settles through settle_payouts instead."""
    rzp = providers.razorpay(db)
    if not rzp.live:
        return
    if event == "settlement.processed":
        s = payload["settlement"]["entity"]
        # Also fires for Flu's own settlements; those contain no Route transfers and match nothing.
        ids = {t["id"] for t in rzp.settlement_transfers(s["id"])}
        _mark_settled(db, ids, s.get("utr"))
    elif event == "transfer.processed":
        t = payload["transfer"]["entity"]
        if t.get("recipient_settlement_id"):
            s = rzp.transfer_settlement(t["id"])
            if s and s.get("utr"):
                _mark_settled(db, {t["id"]}, s["utr"])
    elif event == "transfer.failed":
        t = payload["transfer"]["entity"]
        open_item(db, "reconcile", "transfer_failed", "transfer", t["id"],
                  f"Route transfer {t['id']} failed", {"error": t.get("error"), "notes": t.get("notes")})


def refund(db: Session, org: Org, payment_id: str, amount_paise: int, actor: str) -> dict:
    p = db.get(Payment, payment_id)
    if not p or p.org_id != org.id or p.status != "captured":
        raise not_found("payment")
    if now() - p.captured_at > timedelta(days=7):
        raise bad("refund_window_closed", "unused top-ups are refundable within 7 days")
    allocated = int(db.query(func.coalesce(func.sum(Transfer.amount_paise - Transfer.reversed_paise), 0))
                    .filter(Transfer.payment_id == p.id).scalar())
    if amount_paise > min(available(db, org.id), p.amount_paise - allocated):
        raise conflict("refund_exceeds_available", "refund exceeds the unspent, unreserved balance")
    post(db, org.id, "refund", -amount_paise, "payment", p.id, f"refund:{p.id}:{now().isoformat()}",
         "Refund of unused top-up", actor)
    db.commit()
    return summary(db, org.id)


# ------------------------------------------------------------------ escrow: reserve on hire (Route on_hold)
def reserve_hire(db: Session, hire: Hire, org: Org, actor: str):
    db.query(Wallet).filter_by(org_id=org.id).with_for_update().first()  # serialise reservations per wallet
    if available(db, org.id) < hire.reserved_paise:
        raise conflict("wallet_insufficient", "wallet balance is below this creator's reserve",
                       needed_paise=hire.reserved_paise, available_paise=available(db, org.id))
    post(db, org.id, "reserve", -hire.reserved_paise, "hire", hire.id, f"reserve:{hire.id}", "Reserved on hire", actor)
    ensure_transfers(db, hire)


def ensure_transfers(db: Session, hire: Hire):
    """Create Route transfers on_hold against captured top-ups once the creator has a linked account."""
    kyc = db.get(KycRecord, hire.creator_id)
    if not kyc or not kyc.linked_account_id:
        return
    brief = db.get(Brief, hire.brief_id)
    rzp = providers.razorpay(db)
    db.flush()
    ts = db.query(Transfer).filter_by(hire_id=hire.id).all()
    if rzp.live:
        # A closed hire only needs to cover what the creator is still owed (a KYC hold cleared after close).
        have = sum(t.amount_paise - t.reversed_paise for t in ts)
        closed = hire.status in ("completed", "cancelled")
        need = (owed_net(db, hire) if closed else per_deliverable_cap(brief) * brief.deliverables_per_creator) - have
    else:
        need = per_deliverable_cap(brief) * brief.deliverables_per_creator - sum(t.amount_paise for t in ts)
    for p in db.query(Payment).filter_by(org_id=brief.org_id, status="captured").order_by(Payment.captured_at).all():
        if need <= 0:
            break
        used = int(db.query(func.coalesce(func.sum(Transfer.amount_paise - Transfer.reversed_paise), 0))
                   .filter(Transfer.payment_id == p.id).scalar())
        free = p.amount_paise - used
        if free <= 0:
            continue
        amt = min(free, need)
        if not rzp.live:
            t = rzp.create_transfer(p.rzp_payment_id, kyc.linked_account_id, amt, {"hire_id": hire.id}, on_hold=True)
            db.add(Transfer(hire_id=hire.id, payment_id=p.id, rzp_transfer_id=t["id"], amount_paise=amt, on_hold=True))
            need -= amt
            continue
        for part in escrow_slices(amt):
            try:
                t = rzp.create_transfer(p.rzp_payment_id, kyc.linked_account_id, part, {"hire_id": hire.id}, on_hold=True)
            except ProviderError as e:
                # e.g. the linked account isn't activated yet; the next finalize or KYC change retries.
                open_item(db, "reconcile", "transfer_create_failed", "hire", hire.id,
                          f"Route escrow transfer failed for hire {hire.id}: {e.code}", {"message": str(e)[:300]})
                db.flush()
                return
            db.add(Transfer(hire_id=hire.id, payment_id=p.id, rzp_transfer_id=t["id"], amount_paise=part, on_hold=True))
            need -= part
    db.flush()


def escrow_slices(amount: int) -> list[int]:
    """Route releases a held transfer only in full, so live escrow is split into slices that can be released as
    the creator earns: at most RAZORPAY_ESCROW_MAX_SLICES per chunk, none smaller than the minimum."""
    if amount < RZP_MIN_TRANSFER_PAISE:
        return []
    size = max(settings.razorpay_escrow_min_slice_paise, -(-amount // settings.razorpay_escrow_max_slices))
    parts = [size] * (amount // size)
    rest = amount % size
    if rest and parts and rest < RZP_MIN_TRANSFER_PAISE:
        parts[-1] += rest
    elif rest:
        parts.append(rest)
    return parts


def owed_net(db: Session, hire: Hire) -> int:
    """Net the creator has been paid or is owed on a hire: every finalized batch, settled or not."""
    db.flush()
    ids = [d for (d,) in db.query(Deliverable.id).filter_by(hire_id=hire.id).all()]
    return int(db.query(func.coalesce(func.sum(Payout.net_paise), 0))
               .filter(Payout.deliverable_id.in_(ids or [""]), Payout.status.in_(["processing", "processed"])).scalar())


def route_sync(db: Session, rzp, hire: Hire):
    """Live Route. Release held slices, oldest first, while the creator is owed at least the next slice; the rest
    waits for the next batch. Once the hire is closed, trim the next slice to the exact remainder and reverse every
    other held rupee (Flu's fee, TDS and unspent reserve) back out of escrow. The creator never receives more
    than owed_net, which is what the ledger paid out."""
    owed = owed_net(db, hire)
    ts = db.query(Transfer).filter_by(hire_id=hire.id).order_by(Transfer.created_at, Transfer.id).all()
    released = sum(t.amount_paise - t.reversed_paise for t in ts if not t.on_hold)
    closed = hire.status in ("completed", "cancelled")
    for t in ts:
        held = t.amount_paise - t.reversed_paise
        if not t.on_hold or held <= 0:
            continue
        due = owed - released
        if held > due:
            if not closed:
                break
            # Read the provider's reversed amount first so a retried close never reverses the same rupee twice.
            t.reversed_paise = int(rzp.get_transfer(t.rzp_transfer_id).get("amount_reversed") or 0)
            held, keep = t.amount_paise - t.reversed_paise, max(due, 0)
            if held > keep:
                rzp.reverse_transfer(t.rzp_transfer_id, held - keep)  # POST /v1/transfers/{id}/reversals
                t.reversed_paise += held - keep
                held = keep
            if not held:
                continue
        rzp.release_transfer(t.rzp_transfer_id)  # PATCH /v1/transfers/{id} {on_hold:false}
        t.on_hold = False
        released += held
    db.flush()
    # Point each batch at the released transfer that completes it, so its settlement can mark the batch paid.
    out = [t for t in ts if not t.on_hold and t.amount_paise > t.reversed_paise]
    i = covered = cum = 0
    ids = [d for (d,) in db.query(Deliverable.id).filter_by(hire_id=hire.id).all()]
    for p in db.query(Payout).filter(Payout.deliverable_id.in_(ids or [""]), Payout.status.in_(["processing", "processed"])) \
            .order_by(Payout.created_at, Payout.id).all():
        cum += p.net_paise
        while covered < cum and i < len(out):
            covered += out[i].amount_paise - out[i].reversed_paise
            i += 1
        if covered < cum:
            break
        if not p.rzp_transfer_id:
            p.rzp_transfer_id = out[i - 1].rzp_transfer_id


def _paid(db: Session, p: Payout, utr: str | None):
    p.status, p.utr, p.processed_at = "processed", utr, now()
    notify(db, p.creator_id, "payout_sent", f"₹{p.net_paise / 100:,.2f} sent to your bank. UTR {p.utr}.",
           "/creator/earnings")


def _mark_settled(db: Session, rzp_transfer_ids: set[str], utr: str | None):
    for p in db.query(Payout).filter(Payout.status == "processing",
                                     Payout.rzp_transfer_id.in_(rzp_transfer_ids or [""])).all():
        _paid(db, p, utr)


# ------------------------------------------------------------------ accrual + release
def accrued(db: Session, d: Deliverable, brief: Brief | None = None) -> dict:
    brief = brief or db.get(Brief, db.get(Hire, d.hire_id).brief_id)
    rows = db.query(func.coalesce(func.sum(ViewLedger.delta_views), 0), func.coalesce(func.sum(ViewLedger.accrued_paise), 0)) \
        .filter(ViewLedger.deliverable_id == d.id, ViewLedger.verified.is_(True)).one()
    views, cpm_part = int(rows[0]), int(rows[1])
    flat = brief.flat_paise if brief.pay_model in ("flat", "hybrid") else 0
    if d.status == "rejected":
        flat = cpm_part = 0
    total = min(per_deliverable_cap(brief), flat + cpm_part)
    released = int(db.query(func.coalesce(func.sum(Payout.amount_paise), 0))
                   .filter(Payout.deliverable_id == d.id, Payout.status != "reversed").scalar())
    return {"verified_views": views, "flat_paise": flat, "cpm_paise": cpm_part, "accrued_paise": total,
            "released_paise": released, "unreleased_paise": max(0, total - released)}


def cpm_increment(brief: Brief, verified_total_views: int, cpm_accrued_before: int) -> int:
    """Accrued payout for CPM = min(cap, verified_views x cpm / 1000), recomputed on each accepted delta."""
    if brief.pay_model == "flat":
        return 0
    cpm_cap = brief.cap_paise - (brief.flat_paise if brief.pay_model == "hybrid" else 0)
    target = min(max(cpm_cap, 0), verified_total_views * brief.cpm_paise // 1000)
    return max(0, target - cpm_accrued_before)


def tds_for(db: Session, creator_id: str, gross: int) -> int:
    """Section 194-O: 0.1% of gross; ₹5 lakh FY exemption for individuals with PAN; 5% without PAN (206AA)."""
    kyc = db.get(KycRecord, creator_id)
    if not kyc or not kyc.pan_hash:
        return round(gross * TDS_NO_PAN_RATE)
    t = now().astimezone(IST)
    fy_start = datetime(t.year if t.month >= 4 else t.year - 1, 4, 1, tzinfo=IST)
    cum = int(db.query(func.coalesce(func.sum(Payout.amount_paise), 0))
              .filter(Payout.creator_id == creator_id, Payout.created_at >= fy_start,
                      Payout.status.in_(["processing", "processed"])).scalar())
    if cum + gross <= TDS_194O_EXEMPT_PAISE:
        return 0
    taxable = gross if cum >= TDS_194O_EXEMPT_PAISE else cum + gross - TDS_194O_EXEMPT_PAISE
    return round(taxable * TDS_194O_RATE)


def release(db: Session, d: Deliverable, actor: str | None = None, min_gap: timedelta | None = None) -> Payout | None:
    """Release whatever has accrued since the last batch. Called on approval, when ops clears a held
    delta, at hire close, and from polling with min_gap=24h so creators get one batch a day."""
    if d.status not in ("approved", "auto_approved"):
        return None
    if min_gap:
        last = db.query(func.max(Payout.created_at)).filter(Payout.deliverable_id == d.id).scalar()
        if last and now() - last < min_gap:
            return None
    hire = db.get(Hire, d.hire_id)
    brief = db.get(Brief, hire.brief_id)
    a = accrued(db, d, brief)
    gross = a["unreleased_paise"]
    if gross <= 0:
        return None
    org = db.get(Org, brief.org_id)
    fee = round(gross * take_rate(org))
    p = Payout(creator_id=hire.creator_id, deliverable_id=d.id, org_id=org.id, amount_paise=gross, fee_paise=fee,
               gst_paise=round(fee * GST_RATE), tds_paise=0, net_paise=gross - fee, status="queued")
    db.add(p)
    db.flush()
    kyc = db.get(KycRecord, hire.creator_id)
    if not kyc or kyc.status != "verified":
        p.hold_reason = "kyc_pending"
        notify(db, hire.creator_id, "payout_held_kyc", link="/creator/earnings")
    else:
        finalize(db, p, actor)
    return p


def finalize(db: Session, p: Payout, actor: str | None = None):
    """Post the ledger entries for a payout batch and release the Route transfer."""
    if p.status != "queued":
        return
    d = db.get(Deliverable, p.deliverable_id)
    hire = db.get(Hire, d.hire_id)
    org = db.get(Org, p.org_id)
    p.fee_paise = round(p.amount_paise * take_rate(org))
    p.gst_paise = round(p.fee_paise * GST_RATE)
    p.tds_paise = tds_for(db, p.creator_id, p.amount_paise)
    p.net_paise = p.amount_paise - p.fee_paise - p.tds_paise
    k = f"payout:{p.id}"
    post(db, org.id, "release_reserve", p.amount_paise + p.gst_paise, "hire", hire.id, f"{k}:release", "Released for payout", actor)
    post(db, org.id, "payout", -p.net_paise, "payout", p.id, f"{k}:net", "Creator payout (net)", actor)
    if p.fee_paise:
        post(db, org.id, "fee", -p.fee_paise, "payout", p.id, f"{k}:fee", "Flu platform fee", actor)
    if p.gst_paise:
        post(db, org.id, "fee_gst", -p.gst_paise, "payout", p.id, f"{k}:gst", "GST 18% on platform fee", actor)
    if p.tds_paise:
        post(db, org.id, "tds_withheld", -p.tds_paise, "payout", p.id, f"{k}:tds", "TDS u/s 194-O", actor)
    rzp = providers.razorpay(db)
    if rzp.live:
        # Settles when the released transfer reaches the creator's bank (settlement webhook or settle_payouts).
        p.status = "processing"
        ensure_transfers(db, hire)
        route_sync(db, rzp, hire)
    else:
        ensure_transfers(db, hire)
        for t in db.query(Transfer).filter_by(hire_id=hire.id, on_hold=True).all():
            rzp.release_transfer(t.rzp_transfer_id)  # PATCH /v1/transfers/{id} {on_hold:false}
            t.on_hold = False
        kyc = db.get(KycRecord, p.creator_id)
        p.rzp_transfer_id = rzp.create_settlement(kyc.linked_account_id, p.net_paise, {"payout_id": p.id})["id"]
    seq = db.query(Payout).filter(Payout.invoice_no.isnot(None)).count() + 1
    t = now().astimezone(IST)
    fy = f"{t.year % 100}-{t.year % 100 + 1}" if t.month >= 4 else f"{t.year % 100 - 1}-{t.year % 100}"
    p.invoice_no = f"FLU/{fy}/{seq:06d}"
    p.status, p.hold_reason = "processing", None
    p.settle_after = now() + timedelta(hours=36)  # Route settles T+1 to T+3
    audit(db, actor, "payout.released", "payout", p.id, None,
          {"gross": p.amount_paise, "fee": p.fee_paise, "gst": p.gst_paise, "tds": p.tds_paise, "net": p.net_paise})


def release_kyc_holds(db: Session, creator_id: str):
    for p in db.query(Payout).filter_by(creator_id=creator_id, status="queued").all():
        finalize(db, p, None)
    for h in db.query(Hire).filter_by(creator_id=creator_id).all():
        ensure_transfers(db, h)


def close_hire_if_done(db: Session, hire: Hire, actor: str | None = None, force: bool = False):
    """Return unspent reserve once every deliverable has finished tracking (or was rejected)."""
    if hire.status in ("completed", "cancelled") and not force:
        return
    brief = db.get(Brief, hire.brief_id)
    ds = db.query(Deliverable).filter_by(hire_id=hire.id).all()
    finished = [d for d in ds if d.status == "rejected" or d.tracking_status in ("ended", "frozen")]
    if not force and (len(ds) < brief.deliverables_per_creator or len(finished) < len(ds)):
        return
    if any(d.status in ("submitted", "disputed") for d in ds):
        return  # money still waits on an approval decision
    for d in ds:
        release(db, d, actor)
    released = int(db.query(func.coalesce(func.sum(LedgerEntry.amount_paise), 0))
                   .filter(LedgerEntry.kind == "release_reserve", LedgerEntry.ref_type == "hire",
                           LedgerEntry.ref_id == hire.id).scalar())
    pending = sum(p.amount_paise + p.gst_paise for p in db.query(Payout).filter(
        Payout.deliverable_id.in_([d.id for d in ds] or [""]), Payout.status == "queued").all())
    leftover = hire.reserved_paise - released - pending
    if leftover > 0:
        post(db, brief.org_id, "release_reserve", leftover, "hire", hire.id, f"close:{hire.id}",
             "Unspent reserve returned", actor)
    hire.status = "cancelled" if force and not ds else "completed"
    hire.closed_at = now()
    rzp = providers.razorpay(db)
    if rzp.live:
        route_sync(db, rzp, hire)  # pays out the exact remainder, reverses the rest
        return
    used = sum(p.amount_paise for p in db.query(Payout).filter(Payout.deliverable_id.in_([d.id for d in ds] or [""])).all())
    for t in db.query(Transfer).filter_by(hire_id=hire.id).all():
        spare = t.amount_paise - t.reversed_paise - min(used, t.amount_paise)
        used = max(0, used - t.amount_paise)
        if spare > 0:
            rzp.reverse_transfer(t.rzp_transfer_id, spare)  # POST /v1/transfers/{id}/reversals
            t.reversed_paise += spare


# ------------------------------------------------------------------ recurring jobs
@jobs.task("money.auto_approve_sweep")
def auto_approve_sweep(db: Session):
    t = now()
    for d in db.query(Deliverable).filter(Deliverable.status == "submitted").all():
        if d.approval_deadline_at <= t:
            d.status, d.approved_at = "auto_approved", t
            audit(db, None, "deliverable.auto_approved", "deliverable", d.id, {"status": "submitted"},
                  {"status": "auto_approved"})
            hire = db.get(Hire, d.hire_id)
            notify(db, hire.creator_id, "deliverable_approved", "Auto-approved after 72 hours.", "/creator/work")
            release(db, d)
            jobs.enqueue(db, "scoring.run", {"creator_id": hire.creator_id, "trigger": "deliverable"})
            close_hire_if_done(db, hire)
        elif d.approval_deadline_at - t <= timedelta(hours=24):
            hire = db.get(Hire, d.hire_id)
            brief = db.get(Brief, hire.brief_id)
            from ..models import Notification
            for m in db.query(OrgMember).filter_by(org_id=brief.org_id).all():
                if not db.query(Notification).filter_by(user_id=m.user_id, template="approval_reminder",
                                                        link=f"/brand/briefs/{brief.id}?d={d.id}").first():
                    notify(db, m.user_id, "approval_reminder", "Less than 24 hours left; it auto-approves after that.",
                           f"/brand/briefs/{brief.id}?d={d.id}")
    db.commit()


@jobs.task("money.settle_payouts")
def settle_payouts(db: Session):
    rzp = providers.razorpay(db)
    due = db.query(Payout).filter(Payout.status == "processing", Payout.settle_after <= now())
    if rzp.live:
        # Settlement webhooks normally get here first; this catches any that were missed.
        seen: dict[str, dict | None] = {}
        for p in due.filter(Payout.rzp_transfer_id.isnot(None)).all():
            if p.rzp_transfer_id not in seen:
                seen[p.rzp_transfer_id] = rzp.transfer_settlement(p.rzp_transfer_id)
            s = seen[p.rzp_transfer_id]
            if s and s.get("utr"):
                _paid(db, p, s["utr"])
    else:
        for p in due.all():
            _paid(db, p, rzp.settle(p.rzp_transfer_id)["utr"])
    db.commit()


@jobs.task("money.reconcile")
def reconcile(db: Session) -> dict:
    """Daily: ledger payouts must equal provider settlements (live: every Route transfer must match the provider's
    amount, reversals and hold); top-ups must equal captured payments."""
    rzp = providers.razorpay(db)
    issues = []
    if rzp.live:
        remote = {t["id"]: t for t in rzp.list("transfer")}
        local = db.query(Transfer).all()
        known = {t.rzp_transfer_id for t in local}
        for r in remote.values():
            if r["id"] not in known:  # e.g. created at Razorpay, then our transaction rolled back
                issues.append({"rzp_transfer_id": r["id"], "ledger": None,
                               "provider": {"amount": r["amount"], "on_hold": r.get("on_hold"), "notes": r.get("notes")}})
        for t in local:
            r = remote.get(t.rzp_transfer_id)
            held = t.amount_paise > t.reversed_paise  # a fully reversed transfer's hold flag no longer matters
            mine = {"amount": t.amount_paise, "amount_reversed": t.reversed_paise, "on_hold": t.on_hold if held else None}
            theirs = r and {"amount": r["amount"], "amount_reversed": r.get("amount_reversed") or 0,
                            "on_hold": bool(r.get("on_hold")) if held else None}
            if mine != theirs:
                issues.append({"rzp_transfer_id": t.rzp_transfer_id, "ledger": mine, "provider": theirs})
        settled = remote
    else:
        settled = {s["notes"].get("payout_id"): s for s in rzp.list("settlement")}
        for p in db.query(Payout).filter(Payout.status.in_(["processing", "processed"])).all():
            s = settled.get(p.id)
            if not s or s["amount"] != p.net_paise:
                issues.append({"payout_id": p.id, "ledger_net": p.net_paise, "provider": s and s["amount"]})
    topups = int(db.query(func.coalesce(func.sum(LedgerEntry.amount_paise), 0)).filter(LedgerEntry.kind == "topup").scalar())
    captured = int(db.query(func.coalesce(func.sum(Payment.amount_paise), 0)).filter(Payment.status.in_(["captured", "refunded"])).scalar())
    if topups != captured:
        issues.append({"topups_ledger": topups, "captured_payments": captured})
    if issues:
        open_item(db, "reconcile", "ledger_mismatch", "system", "reconcile",
                  f"Reconciliation found {len(issues)} mismatch(es)", {"issues": issues[:20], "at": now().isoformat()})
    from ..models import SimState
    row = db.get(SimState, "last_reconcile")
    val = {"at": now().isoformat(), "issues": len(issues), "payouts_checked": len(settled), "topups_paise": topups}
    if row:
        row.value = val
    else:
        db.add(SimState(key="last_reconcile", value=val))
    db.commit()
    return val


# ------------------------------------------------------------------ exports
def payouts_csv(db: Session, org_id: str, frm: datetime | None, to: datetime | None) -> str:
    q = db.query(Payout).filter(Payout.org_id == org_id, Payout.status.in_(["processing", "processed"]))
    if frm:
        q = q.filter(Payout.created_at >= frm)
    if to:
        q = q.filter(Payout.created_at <= to)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["invoice_no", "date", "creator", "pan_last4", "brief", "gross_inr", "platform_fee_inr", "gst_on_fee_inr",
                "tds_194o_inr", "net_to_creator_inr", "status", "utr"])
    for p in q.order_by(Payout.created_at).all():
        cp = db.get(CreatorProfile, p.creator_id)
        kyc = db.get(KycRecord, p.creator_id)
        d = db.get(Deliverable, p.deliverable_id)
        brief = db.get(Brief, db.get(Hire, d.hire_id).brief_id)
        w.writerow([p.invoice_no, p.created_at.astimezone(IST).date().isoformat(), cp.display_name,
                    kyc.pan_last4 if kyc else "", brief.title, f"{p.amount_paise / 100:.2f}", f"{p.fee_paise / 100:.2f}",
                    f"{p.gst_paise / 100:.2f}", f"{p.tds_paise / 100:.2f}", f"{p.net_paise / 100:.2f}", p.status, p.utr or ""])
    return buf.getvalue()
