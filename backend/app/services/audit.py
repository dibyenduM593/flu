"""Automated account audit on connect (CR-3), fraud screen (CR-4), niche classification (CR-5),
and Score v0 (CR-7)."""
import statistics
from collections import Counter
from datetime import timedelta, timezone

from sqlalchemy.orm import Session

from .. import providers
from ..clock import now
from ..models import AccountAudit, CreatorProfile, MediaItem, PlatformAccount
from ..providers.base import MediaGone, ProviderError, TokenInvalid
from . import jobs
from .connections import access_token, mark_needs_reauth
from .ops import notify, open_item

IST = timezone(timedelta(hours=5, minutes=30))


def _median(xs, default=0.0):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else default


def _week_key(dt):
    d = dt.astimezone(IST)
    y, w, _ = d.isocalendar()
    return (y, w)


def sync_media(db: Session, acc: PlatformAccount, limit: int = 30) -> list[MediaItem]:
    prov = providers.social_for(acc, db)
    tok = access_token(db, acc)
    prof = prov.profile(tok)
    acc.follower_count = prof.followers
    items = []
    for m in prov.list_media(tok, limit=limit):
        row = db.query(MediaItem).filter_by(platform_account_id=acc.id, external_media_id=m.id).first()
        if not row:
            row = MediaItem(platform_account_id=acc.id, external_media_id=m.id, media_type=m.media_type,
                            media_product_type=m.media_product_type, permalink=m.permalink, caption=m.caption,
                            posted_at=m.timestamp, thumbnail_url=m.thumbnail_url, duration_s=m.duration_s)
            db.add(row)
        try:
            ins = prov.insights(tok, m.id)
            row.last_metrics = {"views": ins.views, "reach": ins.reach, "likes": ins.likes, "comments": ins.comments,
                                "saves": ins.saves, "shares": ins.shares}
            row.metrics_fetched_at = now()
        except MediaGone:
            continue
        except TokenInvalid:
            raise
        except ProviderError:
            pass  # e.g. a post type with no insights: still counts for cadence, not for performance medians
        items.append(row)
    acc.last_synced_at = now()
    db.flush()
    return items, prof, prov, tok


def compute_metrics(items: list[MediaItem], followers: int, followers_30d_ago: int | None) -> dict:
    t = now()
    eng, vr, views, reach, lengths = [], [], [], [], []
    hour_views = Counter()
    hour_n = Counter()
    for m in items:
        x = m.last_metrics or {}
        if not x:
            continue  # no insights for this post; it only counts toward cadence below
        v, r = x.get("views", 0), max(x.get("reach", 0), 1)
        e = x.get("likes", 0) + x.get("comments", 0) + x.get("saves", 0) + x.get("shares", 0)
        eng.append(e / r)
        vr.append(round(v / r, 3))
        views.append(v)
        reach.append(r)
        if m.duration_s:
            lengths.append(m.duration_s)
        h = m.posted_at.astimezone(IST).hour
        hour_views[h] += v
        hour_n[h] += 1
    weeks = Counter(_week_key(m.posted_at) for m in items if t - m.posted_at <= timedelta(weeks=8))
    weeks_active = sum(1 for c in weeks.values() if c >= 2)
    posts_8w = sum(weeks.values())
    f = max(followers, 1)
    growth = None
    if followers_30d_ago:
        growth = (followers - followers_30d_ago) / max(followers_30d_ago, 1)
    best_hours = sorted(hour_n, key=lambda h: hour_views[h] / hour_n[h], reverse=True)[:3]
    sv = sorted(views)
    q = lambda p: sv[min(len(sv) - 1, int(p * len(sv)))] if sv else 0
    return {
        "posts_analysed": len(views),
        "posts_without_insights": len(items) - len(views),
        "followers": followers,
        "engagement_rate": round(_median(eng), 4),
        "median_views": int(_median(views)),
        "views_p25": q(0.25), "views_p75": q(0.75),
        "median_reach": int(_median(reach)),
        "reach_ratio": round(_median(reach) / f, 3),
        "view_follower_ratio": round(_median(views) / f, 3),
        "posts_per_week": round(posts_8w / 8, 2),
        "weeks_active_8": weeks_active,
        "follower_growth_30d": round(growth, 4) if growth is not None else None,
        "views_per_reach": vr,
        "median_length_s": int(_median(lengths)) if lengths else None,
        "best_hours_ist": best_hours,
    }


def fraud_screen(metrics: dict, comments: list[str]) -> list[str]:
    flags = []
    if metrics["view_follower_ratio"] > 50 and metrics["engagement_rate"] < 0.005:
        flags.append("views_without_engagement")
    if (metrics.get("follower_growth_30d") or 0) > 0.30:
        flags.append("follower_spike")
    if comments:
        dup = 1 - len(set(c.strip().lower() for c in comments)) / len(comments)
        if dup > 0.40:
            flags.append("duplicate_comments")
    return flags


def streak_weeks(db: Session, creator_id: str) -> int:
    """Consecutive IST weeks (ending this or last week) with >= 3 posts across connected accounts."""
    accs = [a.id for a in db.query(PlatformAccount).filter_by(creator_id=creator_id).all()]
    if not accs:
        return 0
    posts = db.query(MediaItem.posted_at).filter(MediaItem.platform_account_id.in_(accs)).all()
    weeks = Counter(_week_key(p[0]) for p in posts)
    streak, d = 0, now()
    if weeks.get(_week_key(d), 0) < 3:
        d -= timedelta(weeks=1)  # the current week is still in progress
    while weeks.get(_week_key(d), 0) >= 3:
        streak += 1
        d -= timedelta(weeks=1)
    return streak


@jobs.task("audit.run")
def run(db: Session, platform_account_id: str):
    acc = db.get(PlatformAccount, platform_account_id)
    if not acc or acc.status != "active":
        return
    try:
        items, prof, prov, tok = sync_media(db, acc)
    except TokenInvalid:
        mark_needs_reauth(db, acc)
        db.commit()
        return
    metrics = compute_metrics(items, prof.followers, prof.followers_30d_ago)
    top = sorted(items, key=lambda m: (m.last_metrics or {}).get("views", 0), reverse=True)[:3]
    comments = []
    for m in top:
        try:
            comments += prov.comment_sample(tok, m.external_media_id)
        except ProviderError:
            pass  # comment text needs instagram_business_manage_comments; the duplicate check is skipped without it
    flags = fraud_screen(metrics, comments)
    result = "flag" if flags else "pass"
    audit_row = AccountAudit(platform_account_id=acc.id, metrics=metrics, fraud_flags=flags, result=result)
    db.add(audit_row)
    db.flush()
    cp = db.get(CreatorProfile, acc.creator_id)
    if flags:
        open_item(db, "fraud_flag", flags[0], "platform_account", acc.id,
                  f"@{acc.handle} ({acc.platform}) flagged: {', '.join(flags)}",
                  {"audit_id": audit_row.id, "flags": flags, "metrics": {k: v for k, v in metrics.items()
                                                                         if k != "views_per_reach"}})
        notify(db, acc.creator_id, "audit_flagged", link="/creator")
    else:
        notify(db, acc.creator_id, "audit_passed", link="/creator/score")
    refresh_eligibility(db, cp)

    # CR-5: niche classification on captions unless the creator has confirmed their niches.
    if not cp.niches_confirmed:
        from .ai import niche_classify
        res = niche_classify(db, [m.caption or "" for m in items], created_by=cp.user_id)
        cp.niches = [n["niche"] for n in res["niches"]][:3]
        cp.niche_confidence = {n["niche"]: n["confidence"] for n in res["niches"]}
    db.flush()
    from .scoring import run_score
    run_score(db, cp.user_id, trigger="audit")
    db.commit()


def refresh_eligibility(db: Session, cp: CreatorProfile):
    """Eligible when every active account's latest audit passed (or ops cleared the flag)."""
    ok, any_acc = True, False
    for acc in db.query(PlatformAccount).filter_by(creator_id=cp.user_id, status="active").all():
        any_acc = True
        a = (db.query(AccountAudit).filter_by(platform_account_id=acc.id)
             .order_by(AccountAudit.run_at.desc()).first())
        if not a or a.result != "pass":
            ok = False
    cp.eligible = ok and any_acc


def latest_audit(db: Session, acc_id: str) -> AccountAudit | None:
    return (db.query(AccountAudit).filter_by(platform_account_id=acc_id)
            .order_by(AccountAudit.run_at.desc()).first())
