from datetime import datetime, timedelta, timezone

from app.models import AccountAudit, CreatorProfile, OpsItem, ViewSnapshot
from app.services import scoring
from app.services.tracking import check_anomaly


def _snap(t, views, likes=0):
    return ViewSnapshot(polled_at=t, views=views, reach=int(views * 0.8), likes=likes, comments=0, saves=0, shares=0)


T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


def test_a6_holds_spike_without_engagement():
    snaps = [_snap(T0 + timedelta(hours=1), 1000, 60), _snap(T0 + timedelta(hours=7), 4000, 240)]
    new = _snap(T0 + timedelta(hours=13), 400_000, 260)
    assert check_anomaly(snaps, new, followers=20_000, posted_at=T0) is not None


def test_a6_passes_organic_growth():
    snaps = [_snap(T0 + timedelta(hours=1), 1000, 60), _snap(T0 + timedelta(hours=7), 4000, 240)]
    new = _snap(T0 + timedelta(hours=13), 9000, 540)
    assert check_anomaly(snaps, new, followers=20_000, posted_at=T0) is None


def test_a6_holds_views_far_above_followers():
    new = _snap(T0 + timedelta(hours=1), 900_000, 100)
    assert check_anomaly([], new, followers=5_000, posted_at=T0) is not None


def test_seeded_bot_views_were_held(db):
    assert db.query(ViewSnapshot).filter_by(anomaly="held").count() >= 1
    assert db.query(OpsItem).filter_by(type="view_anomaly").count() >= 1


def test_fraud_screen_flags_planted_accounts(db):
    flags = [f for a in db.query(AccountAudit).all() for f in a.fraud_flags]
    assert "views_without_engagement" in flags and "duplicate_comments" in flags


def test_score_bounds_and_tiers(db):
    for cp in db.query(CreatorProfile).all():
        assert 0 <= float(cp.score) <= 100
        assert cp.tier == scoring.tier_for(float(cp.score))
    assert scoring.tier_for(80) == "platinum" and scoring.tier_for(79.9) == "gold"
    assert scoring.tier_for(40) == "silver" and scoring.tier_for(39.9) == "bronze"


def test_score_breakdown_has_weights_summing_to_one(db):
    cp = db.query(CreatorProfile).filter_by(eligible=True).first()
    res = scoring.compute(db, cp.user_id)
    assert abs(sum(v["weight"] for v in res["breakdown"].values()) - 1.0) < 1e-9
    assert abs(sum(v["points"] for v in res["breakdown"].values()) - res["score"]) < 0.05
