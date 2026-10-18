"""Ledger properties: balances derived, never negative, reserve covers releases, idempotent posting."""
from hypothesis import given, settings as hsettings, strategies as st
from sqlalchemy import func

from app.models import Hire, LedgerEntry, Org, Payout
from app.services import money


def test_balances_never_negative_and_reconcile(db):
    for org in db.query(Org).all():
        s = money.summary(db, org.id)
        assert s["available_paise"] >= 0
        assert s["reserved_paise"] >= 0
        assert s["topped_up_paise"] - s["refunded_paise"] == s["available_paise"] + s["reserved_paise"] + s["spent_paise"]


def test_release_never_exceeds_reserve(db):
    for h in db.query(Hire).all():
        released = db.query(func.coalesce(func.sum(LedgerEntry.amount_paise), 0)).filter(
            LedgerEntry.kind == "release_reserve", LedgerEntry.ref_type == "hire", LedgerEntry.ref_id == h.id).scalar()
        assert released <= h.reserved_paise


def test_payout_arithmetic(db):
    for p in db.query(Payout).all():
        assert p.net_paise == p.amount_paise - p.fee_paise - p.tds_paise
        assert p.gst_paise == round(p.fee_paise * 0.18)


def test_post_is_idempotent(db):
    org = db.query(Org).first()
    before = money.available(db, org.id)
    money.post(db, org.id, "adjustment", 100, "test", "x", "test:idem")
    money.post(db, org.id, "adjustment", 100, "test", "x", "test:idem")
    assert money.available(db, org.id) == before + 100
    db.rollback()


def test_sign_enforced(db):
    org = db.query(Org).first()
    try:
        money.post(db, org.id, "reserve", 500, "test", "x", "test:sign")
        raise AssertionError("positive reserve must be rejected")
    except ValueError:
        pass
    db.rollback()


class _B:
    def __init__(self, pay_model, cpm, flat, cap):
        self.pay_model, self.cpm_paise, self.flat_paise, self.cap_paise = pay_model, cpm, flat, cap


@hsettings(max_examples=200, deadline=None)
@given(st.sampled_from(["cpm", "hybrid"]), st.integers(100, 20000), st.integers(0, 500_00),
       st.integers(1_000_00, 50_000_00), st.lists(st.integers(0, 200_000), min_size=1, max_size=40))
def test_cpm_accrual_is_capped_and_monotonic(model, cpm, flat, cap, deltas):
    b = _B(model, cpm, flat if model == "hybrid" else 0, max(cap, flat + 1))
    total_views, accrued = 0, 0
    for dv in deltas:
        total_views += dv
        inc = money.cpm_increment(b, total_views, accrued)
        assert inc >= 0
        accrued += inc
    cpm_cap = b.cap_paise - (b.flat_paise if model == "hybrid" else 0)
    assert accrued == min(cpm_cap, total_views * cpm // 1000)


def test_tds_194o_exemption_and_rate(db, monkeypatch):
    from app.models import KycRecord
    rec = db.query(KycRecord).filter(KycRecord.pan_hash.isnot(None)).first()
    assert money.tds_for(db, rec.creator_id, 10_000_00) == 0  # under the ₹5 lakh FY exemption
    assert money.tds_for(db, "no-kyc-creator", 10_000_00) == 50_000  # 5% without PAN (206AA)
