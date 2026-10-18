"""Creator Score (A1, phase 1): deterministic formula over audit features, percentiles within
the creator's primary-niche cohort. Phase 2 (LightGBM on verified 7-day views) replaces
`_formula` once >= 2,000 completed deliverables exist; every run is logged to score_runs with
its feature vector so that dataset accumulates from day one.

S = 100 * (0.30 q_eng + 0.25 q_reach + 0.20 q_cons + 0.15 q_growth + 0.10 q_hook)
"""
import statistics

from sqlalchemy.orm import Session

from ..config import TIERS
from ..models import CreatorProfile, Deliverable, Hire, PlatformAccount, ScoreRun
from . import jobs
from .audit import latest_audit, streak_weeks

MODEL_VERSION = "formula-v0"
WEIGHTS = {"eng": 0.30, "reach": 0.25, "cons": 0.20, "growth": 0.15, "hook": 0.10}
LABELS = {
    "eng": ("Engagement", "Median (likes + comments + saves + shares) / reach over your last 30 posts"),
    "reach": ("Discovery", "Median reach / followers. Rewards reaching beyond your followers"),
    "cons": ("Consistency", "Weeks out of the last 8 with at least 2 posts"),
    "growth": ("Growth", "30-day follower growth, clipped at ±50%"),
    "hook": ("Hook strength", "Share of your Reels whose views/reach beat your niche median"),
}
TIPS = {
    "eng": "End every Reel with a question or a save-worthy checklist; reply to comments in the first hour.",
    "reach": "Lead with the payoff in the first 2 seconds and use trending audio so Reels travel to non-followers.",
    "cons": "Post at least 2 Reels every week for the next 4 weeks; batch-shoot on one day.",
    "growth": "Collab with a creator in an adjacent niche and pin your best Reel to the top of your profile.",
    "hook": "Open with a bold on-screen line (number, contrarian take or before/after) before any intro.",
}


def tier_for(score: float) -> str:
    for name, floor in TIERS:
        if score >= floor:
            return name
    return "bronze"


def next_tier(score: float):
    for name, floor in reversed(TIERS):
        if score < floor:
            return name, floor
    return None, None


def primary_account(db: Session, creator_id: str) -> PlatformAccount | None:
    accs = db.query(PlatformAccount).filter_by(creator_id=creator_id, status="active").all()
    accs = [a for a in accs if latest_audit(db, a.id)]
    return max(accs, key=lambda a: a.follower_count, default=None)


def raw_features(db: Session, creator_id: str) -> dict | None:
    acc = primary_account(db, creator_id)
    if not acc:
        return None
    a = latest_audit(db, acc.id)
    m = a.metrics
    growth = m.get("follower_growth_30d")
    return {
        "platform": acc.platform,
        "eng": m["engagement_rate"],
        "reach": m["reach_ratio"],
        "cons": m["weeks_active_8"] / 8,
        "growth": max(-0.5, min(0.5, growth if growth is not None else 0.0)),
        "vr": m.get("views_per_reach", []),
        "median_views": m["median_views"],
        "followers": m["followers"],
    }


def _pct(value: float, cohort: list[float]) -> float:
    if not cohort:
        return 0.5
    below = sum(1 for c in cohort if c < value)
    equal = sum(1 for c in cohort if c == value)
    return (below + 0.5 * equal) / len(cohort)


def _cohort(db: Session, niche: str | None) -> list[tuple[str, dict]]:
    rows = []
    for cp in db.query(CreatorProfile).all():
        f = raw_features(db, cp.user_id)
        if f:
            rows.append((cp, f))
    same = [(cp.user_id, f) for cp, f in rows if niche and cp.niches and cp.niches[0] == niche]
    return same if len(same) >= 5 else [(cp.user_id, f) for cp, f in rows]


def compute(db: Session, creator_id: str) -> dict | None:
    cp = db.get(CreatorProfile, creator_id)
    f = raw_features(db, creator_id)
    if not f:
        return None
    cohort = _cohort(db, cp.niches[0] if cp.niches else None)
    all_vr = [x for _, g in cohort for x in g["vr"]]
    niche_vr_median = statistics.median(all_vr) if all_vr else 1.0

    def hook_share(vr):
        return sum(1 for x in vr if x >= niche_vr_median) / len(vr) if vr else 0.0

    f["hook"] = hook_share(f["vr"])
    cohort_vals = {k: [g[k] if k != "hook" else hook_share(g["vr"]) for _, g in cohort] for k in WEIGHTS}
    q = {k: _pct(f[k], cohort_vals[k]) for k in WEIGHTS}
    score = round(100 * sum(WEIGHTS[k] * q[k] for k in WEIGHTS), 2)
    breakdown = {}
    for k in WEIGHTS:
        gain = 100 * WEIGHTS[k] * (min(1.0, q[k] + 0.25) - q[k])
        breakdown[k] = {"label": LABELS[k][0], "definition": LABELS[k][1], "value": round(f[k], 4),
                        "percentile": round(q[k], 3), "weight": WEIGHTS[k],
                        "points": round(100 * WEIGHTS[k] * q[k], 2), "gain_if_top_quartile_step": round(gain, 2),
                        "tip": TIPS[k]}
    lever = max(breakdown, key=lambda k: breakdown[k]["gain_if_top_quartile_step"])
    nt, floor = next_tier(score)
    return {
        "score": score, "tier": tier_for(score), "breakdown": breakdown,
        "fastest_lever": {"feature": lever, **breakdown[lever]},
        "next_tier": nt, "points_to_next_tier": round(floor - score, 2) if floor is not None else None,
        "cohort": {"niche": cp.niches[0] if cp.niches else None, "size": len(cohort),
                   "niche_views_per_reach_median": round(niche_vr_median, 3)},
        "features": {k: v for k, v in f.items() if k != "vr"},
        "model_version": MODEL_VERSION,
    }


def run_score(db: Session, creator_id: str, trigger: str = "manual") -> dict | None:
    res = compute(db, creator_id)
    if not res:
        return None
    cp = db.get(CreatorProfile, creator_id)
    cp.score, cp.tier = res["score"], res["tier"]
    cp.streak_weeks = streak_weeks(db, creator_id)
    completed = (db.query(Deliverable).join(Hire, Hire.id == Deliverable.hire_id)
                 .filter(Hire.creator_id == creator_id, Deliverable.status.in_(["approved", "auto_approved"])).count())
    cp.points = completed * 50 + cp.streak_weeks * 10
    db.add(ScoreRun(creator_id=creator_id, features=res["features"], breakdown=res["breakdown"],
                    score=res["score"], tier=res["tier"], model_version=MODEL_VERSION, trigger=trigger))
    db.flush()
    return res


@jobs.task("scoring.run")
def score_job(db: Session, creator_id: str, trigger: str = "job"):
    run_score(db, creator_id, trigger)
    db.commit()


@jobs.task("scoring.nightly_batch")
def nightly(db: Session):
    for cp in db.query(CreatorProfile).all():
        run_score(db, cp.user_id, trigger="nightly")
    db.commit()
