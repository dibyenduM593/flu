"""Tracking and view verification (M5, A6).

Poll schedule (TR-1): +1 h, +6 h, +24 h, then every 6 h until the brief's tracking window
(30 d default), then daily (stats only, no accrual) to 90 d. Every read is stored append-only in
view_snapshots; accepted deltas become view_ledger rows, which are the payout source of truth.
"""
from datetime import timedelta

from sqlalchemy.orm import Session

from .. import providers
from ..clock import now
from ..models import (Brief, Deliverable, Hire, MediaItem, OrgMember, PlatformAccount, ViewLedger, ViewSnapshot)
from ..providers.base import MediaGone, TokenInvalid
from . import jobs
from .connections import access_token, mark_needs_reauth
from .ops import notify, open_item

SPIKE_MULTIPLE = 10        # delta > 10x trailing 6-h rate ...
SPIKE_ENG_RATIO = 0.002    # ... while engagement delta < 0.2% of view delta
FOLLOWER_MULTIPLE = 100    # or cumulative views / followers > 100x ...
FOLLOWER_ENG_RATIO = 0.003  # ... with engagement < 0.3%
STATS_ONLY_DAYS = 90


def next_poll_at(d: Deliverable, last):
    start = d.submitted_at
    age = last - start
    if age < timedelta(hours=1):
        return start + timedelta(hours=1)
    if age < timedelta(hours=6):
        return start + timedelta(hours=6)
    if age < timedelta(hours=24):
        return start + timedelta(hours=24)
    if last < d.tracking_ends_at:
        return min(last + timedelta(hours=6), d.tracking_ends_at)
    if age < timedelta(days=STATS_ONLY_DAYS):
        return last + timedelta(days=1)
    return None


def schedule_next(db: Session, d: Deliverable, after):
    t = next_poll_at(d, after)
    d.next_poll_at = t
    if t:
        jobs.enqueue(db, "tracking.poll", {"deliverable_id": d.id}, t, dedupe=f"poll:{d.id}:{t.isoformat()}")


def _eng(s) -> int:
    return s.likes + s.comments + s.saves + s.shares


def check_anomaly(snaps: list[ViewSnapshot], new: ViewSnapshot, followers: int, posted_at) -> str | None:
    """A6. Returns a reason if the delta must be held for ops review."""
    prev = snaps[-1] if snaps else None
    dv = new.views - (prev.views if prev else 0)
    de = _eng(new) - (_eng(prev) if prev else 0)
    if prev and dv > 0:
        hours = max((new.polled_at - prev.polled_at).total_seconds() / 3600, 0.1)
        base = next((s for s in reversed(snaps[:-1]) if s.polled_at <= prev.polled_at - timedelta(hours=6)), None)
        if base:
            rate = (prev.views - base.views) / max((prev.polled_at - base.polled_at).total_seconds() / 3600, 0.1)
        else:
            rate = prev.views / max((prev.polled_at - posted_at).total_seconds() / 3600, 1)
        if dv > SPIKE_MULTIPLE * max(rate, 1) * hours and de / dv < SPIKE_ENG_RATIO:
            return f"views +{dv:,} in {hours:.0f} h (>{SPIKE_MULTIPLE}x trailing rate) with engagement +{de}"
    if followers and new.views / followers > FOLLOWER_MULTIPLE and _eng(new) / max(new.views, 1) < FOLLOWER_ENG_RATIO:
        return f"views are {new.views / followers:.0f}x followers with {_eng(new) / max(new.views, 1):.2%} engagement"
    return None


def accept_delta(db: Session, d: Deliverable, snap: ViewSnapshot, delta: int, brief: Brief):
    from .money import cpm_increment
    if db.query(ViewLedger).filter_by(snapshot_id=snap.id).first():
        return
    rows = db.query(ViewLedger).filter_by(deliverable_id=d.id, verified=True).all()
    total_views = sum(r.delta_views for r in rows) + delta
    before = sum(r.accrued_paise for r in rows)
    inc = cpm_increment(brief, total_views, before)
    db.add(ViewLedger(deliverable_id=d.id, snapshot_id=snap.id, delta_views=delta, verified=True, accrued_paise=inc))
    db.flush()


@jobs.task("tracking.poll")
def poll(db: Session, deliverable_id: str):
    from .money import close_hire_if_done, release
    d = db.get(Deliverable, deliverable_id)
    if not d or d.tracking_status == "frozen" or d.status == "rejected":
        return
    hire = db.get(Hire, d.hire_id)
    brief = db.get(Brief, hire.brief_id)
    media = db.get(MediaItem, d.media_item_id)
    acc = db.get(PlatformAccount, media.platform_account_id)
    prov = providers.social(acc.platform, db)
    t = now()
    try:
        if acc.platform == "instagram":
            ins = prov.insights(access_token(db, acc), media.external_media_id)
        elif hasattr(prov, "public_insights"):
            ins = prov.public_insights(media.external_media_id)  # YouTube stats need only an API key
        else:
            ins = prov.insights(None, media.external_media_id)
    except TokenInvalid:
        # Gap: tracking pauses until the creator reconnects; the gap is never paid as estimated views.
        mark_needs_reauth(db, acc)
        schedule_next(db, d, t)
        db.commit()
        return
    except MediaGone:
        d.tracking_status = "frozen"  # TR-4: accrued-but-unapproved amount is frozen
        notify(db, hire.creator_id, "post_deleted", link="/creator/work")
        for m in db.query(OrgMember).filter_by(org_id=brief.org_id).all():
            notify(db, m.user_id, "post_deleted", f"A post on “{brief.title}” was deleted or made private.",
                   f"/brand/briefs/{brief.id}")
        close_hire_if_done(db, hire)
        db.commit()
        return
    snaps = (db.query(ViewSnapshot).filter_by(deliverable_id=d.id).order_by(ViewSnapshot.polled_at).all())
    snap = ViewSnapshot(deliverable_id=d.id, polled_at=t, views=ins.views, reach=ins.reach, likes=ins.likes,
                        comments=ins.comments, saves=ins.saves, shares=ins.shares, raw=ins.raw)
    db.add(snap)
    db.flush()
    media.last_metrics = {"views": ins.views, "reach": ins.reach, "likes": ins.likes, "comments": ins.comments,
                          "saves": ins.saves, "shares": ins.shares}
    media.metrics_fetched_at = t
    delta = max(0, ins.views - (snaps[-1].views if snaps else 0))
    in_window = t <= d.tracking_ends_at
    if in_window and delta > 0:
        reason = check_anomaly(snaps, snap, acc.follower_count, media.posted_at)
        if reason:
            snap.anomaly, snap.anomaly_reason = "held", reason
            open_item(db, "view_anomaly", "view_spike", "view_snapshot", snap.id,
                      f"Held {delta:,} views on @{acc.handle} for “{brief.title}”",
                      {"deliverable_id": d.id, "delta_views": delta, "reason": reason})
        else:
            accept_delta(db, d, snap, delta, brief)
            release(db, d, min_gap=timedelta(hours=24))
    if not in_window and d.tracking_status == "tracking":
        d.tracking_status = "ended"
        close_hire_if_done(db, hire)
    schedule_next(db, d, t)
    db.commit()


def clear_snapshot(db: Session, snap: ViewSnapshot, decision: str):
    """Ops decision on a held delta: 'cleared' accrues it, 'rejected' drops it for good."""
    from .money import release
    if snap.anomaly != "held":
        return
    d = db.get(Deliverable, snap.deliverable_id)
    brief = db.get(Brief, db.get(Hire, d.hire_id).brief_id)
    prev = (db.query(ViewSnapshot).filter(ViewSnapshot.deliverable_id == d.id, ViewSnapshot.polled_at < snap.polled_at)
            .order_by(ViewSnapshot.polled_at.desc()).first())
    snap.anomaly = decision
    if decision == "cleared":
        accept_delta(db, d, snap, max(0, snap.views - (prev.views if prev else 0)), brief)
        release(db, d)


def start(db: Session, d: Deliverable):
    jobs.enqueue(db, "tracking.poll", {"deliverable_id": d.id}, now(), dedupe=f"poll:{d.id}:initial")
