"""Matching engine (M4): eligibility MT-1, applicant ranking MT-2, brief ranking MT-3."""
import statistics

from sqlalchemy.orm import Session

from ..clock import now
from ..config import TIER_ORDER, settings
from ..models import (Application, Brief, CreatorProfile, Deliverable, Hire, MediaItem, PlatformAccount, ViewLedger)
from .audit import latest_audit
from .money import per_deliverable_cap


def creator_platforms(db: Session, creator_id: str) -> dict[str, PlatformAccount]:
    return {a.platform: a for a in db.query(PlatformAccount).filter_by(creator_id=creator_id, status="active").all()}


def eligibility(db: Session, cp: CreatorProfile, brief: Brief) -> tuple[bool, list[str]]:
    reasons = []
    if brief.status != "live":
        reasons.append("brief is not live")
    if TIER_ORDER.get(cp.tier, 0) < TIER_ORDER.get(brief.min_tier, 0):
        reasons.append(f"needs {brief.min_tier.title()} tier or above")
    if brief.niches and not set(cp.niches or []) & set(brief.niches):
        reasons.append("niche does not match")
    if brief.cities and (cp.city or "") not in brief.cities:
        reasons.append("city not in the brief's list")
    if not cp.eligible:
        reasons.append("account audit not passed yet")
    if not set(creator_platforms(db, cp.user_id)) & set(brief.platforms):
        reasons.append("connect " + " or ".join(p.title() for p in brief.platforms))
    if brief.deadline and brief.deadline < now():
        reasons.append("deadline passed")
    hired = db.query(Hire).filter(Hire.brief_id == brief.id, Hire.status != "cancelled").count()
    if hired >= brief.max_creators:
        reasons.append("brief is full")
    return not reasons, reasons


def median_views(db: Session, creator_id: str, platforms: list[str]) -> int:
    best = 0
    for p, acc in creator_platforms(db, creator_id).items():
        if p in platforms:
            a = latest_audit(db, acc.id)
            if a:
                best = max(best, a.metrics.get("median_views", 0))
    return best


def flu_history(db: Session, creator_id: str) -> dict:
    """Past Flu results: verified views per deliverable and on-time rate."""
    ds = (db.query(Deliverable, Hire).join(Hire, Hire.id == Deliverable.hire_id)
          .filter(Hire.creator_id == creator_id).all())
    views = []
    on_time = 0
    for d, h in ds:
        v = sum(x.delta_views for x in db.query(ViewLedger).filter_by(deliverable_id=d.id, verified=True).all())
        views.append(v)
        b = db.get(Brief, h.brief_id)
        if not b.deadline or d.submitted_at <= b.deadline:
            on_time += 1
    return {"deliverables": len(ds), "median_verified_views": int(statistics.median(views)) if views else None,
            "on_time_rate": on_time / len(ds) if ds else None}


def expected_earnings(db: Session, creator_id: str, brief: Brief) -> dict:
    """MT-3: min(cap, predictedViews x CPM / 1000) using the creator's median views (+ base for hybrid/flat)."""
    hist = flu_history(db, creator_id)
    mv = hist["median_verified_views"] or median_views(db, creator_id, brief.platforms)
    cap = per_deliverable_cap(brief)
    if brief.pay_model == "flat":
        per = brief.flat_paise
    elif brief.pay_model == "cpm":
        per = min(cap, mv * brief.cpm_paise // 1000)
    else:
        per = min(cap, brief.flat_paise + mv * brief.cpm_paise // 1000)
    return {"predicted_views": mv, "per_deliverable_paise": per,
            "total_paise": per * brief.deliverables_per_creator, "cap_paise": cap}


def niche_fit(cp: CreatorProfile, brief: Brief) -> float:
    if not brief.niches:
        return 0.6
    ns = cp.niches or []
    if ns and ns[0] in brief.niches:
        return 1.0
    if set(ns) & set(brief.niches):
        return 0.7
    return 0.2


def rank(db: Session, app: Application) -> tuple[float, dict]:
    """MT-2: 0.45 x Score + 0.25 x nicheFit + 0.15 x historicalCPMfit + 0.15 x responsiveness."""
    w = settings.rank_weights
    cp = db.get(CreatorProfile, app.creator_id)
    brief = db.get(Brief, app.brief_id)
    ee = expected_earnings(db, cp.user_id, brief)
    # Value for the brand: expected views relative to what the cap buys at the brief's CPM.
    cap_views = (per_deliverable_cap(brief) * 1000 // brief.cpm_paise) if brief.cpm_paise else 0
    cpm_fit = min(1.0, ee["predicted_views"] / cap_views) if cap_views else 0.5
    hist = flu_history(db, cp.user_id)
    hours = max(0.0, ((app.created_at - brief.published_at).total_seconds() / 3600) if brief.published_at else 24)
    speed = 1 - min(1.0, hours / 72)
    resp = speed if hist["on_time_rate"] is None else 0.5 * speed + 0.5 * hist["on_time_rate"]
    parts = {"score": float(cp.score) / 100, "niche": niche_fit(cp, brief), "cpm": cpm_fit, "responsiveness": resp}
    total = round(sum(w[k] * parts[k] for k in w), 4)
    return total, {"weights": w, "parts": {k: round(v, 3) for k, v in parts.items()},
                   "expected": ee, "history": hist}


def sample_posts(db: Session, creator_id: str, n: int = 3) -> list[dict]:
    accs = [a.id for a in creator_platforms(db, creator_id).values()]
    if not accs:
        return []
    rows = db.query(MediaItem).filter(MediaItem.platform_account_id.in_(accs)).all()
    rows.sort(key=lambda m: -(m.last_metrics or {}).get("views", 0))
    return [{"permalink": m.permalink, "caption": (m.caption or "")[:90], "views": (m.last_metrics or {}).get("views", 0)}
            for m in rows[:n]]
