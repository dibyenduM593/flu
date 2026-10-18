"""Response shapes shared by routers. Never include tokens, raw PAN or bank numbers."""
from sqlalchemy.orm import Session

from .models import (Application, Brief, Contract, CreatorProfile, Deliverable, Dispute, Hire, MediaItem, Org,
                     PlatformAccount, Payout, ViewSnapshot)
from .services import money


def brief(db: Session, b: Brief, org: Org | None = None, full: bool = True) -> dict:
    org = org or db.get(Org, b.org_id)
    out = {
        "id": b.id, "org": {"id": org.id, "name": org.name, "category": org.category, "city": org.city,
                            "verified": bool(org.gst_verified or org.gstin), "instagram_handle": org.instagram_handle},
        "title": b.title, "product": b.product, "goal": b.goal, "platforms": b.platforms,
        "deliverable_type": b.deliverable_type, "deliverables_per_creator": b.deliverables_per_creator,
        "pay_model": b.pay_model, "cpm_paise": b.cpm_paise, "flat_paise": b.flat_paise, "cap_paise": b.cap_paise,
        "min_tier": b.min_tier, "niches": b.niches, "cities": b.cities, "max_creators": b.max_creators,
        "deadline": b.deadline, "usage_rights": b.usage_rights, "tracking_days": b.tracking_days, "status": b.status,
        "published_at": b.published_at, "created_at": b.created_at,
        "hired_count": db.query(Hire).filter(Hire.brief_id == b.id, Hire.status != "cancelled").count(),
        "application_count": db.query(Application).filter_by(brief_id=b.id).count(),
    }
    if full:
        out.update({
            "required_elements": b.required_elements, "dos": b.dos, "donts": b.donts, "policy_flags": b.policy_flags,
            "ai_draft_id": b.ai_draft_id,
            "angles": [{"id": a.id, "title": a.title, "hook": a.hook, "angle_text": a.angle_text, "format": a.format,
                        "length_s": a.length_s, "why_now": a.why_now, "trend_ref": a.trend_ref, "source": a.source}
                       for a in b.angles],
            "reserve_per_creator_paise": money.reserve_for(b, org),
        })
    return out


def creator_card(db: Session, cp: CreatorProfile) -> dict:
    accs = db.query(PlatformAccount).filter_by(creator_id=cp.user_id, status="active").all()
    return {"id": cp.user_id, "display_name": cp.display_name, "city": cp.city, "niches": cp.niches, "tier": cp.tier,
            "score": float(cp.score), "streak_weeks": cp.streak_weeks, "eligible": cp.eligible,
            "accounts": [{"platform": a.platform, "handle": a.handle, "followers": a.follower_count} for a in accs]}


def snapshot(s: ViewSnapshot) -> dict:
    return {"id": s.id, "polled_at": s.polled_at, "views": s.views, "reach": s.reach, "likes": s.likes,
            "comments": s.comments, "saves": s.saves, "shares": s.shares, "anomaly": s.anomaly,
            "anomaly_reason": s.anomaly_reason}


def deliverable(db: Session, d: Deliverable, with_snaps: bool = False) -> dict:
    hire = db.get(Hire, d.hire_id)
    b = db.get(Brief, hire.brief_id)
    m = db.get(MediaItem, d.media_item_id)
    acc = db.get(PlatformAccount, m.platform_account_id)
    a = money.accrued(db, d, b)
    out = {"id": d.id, "hire_id": d.hire_id, "brief_id": b.id, "brief_title": b.title, "post_url": d.post_url,
           "platform": acc.platform, "handle": acc.handle, "caption": m.caption, "submitted_at": d.submitted_at,
           "status": d.status, "approval_deadline_at": d.approval_deadline_at, "approved_at": d.approved_at,
           "tracking_status": d.tracking_status, "tracking_ends_at": d.tracking_ends_at, "next_poll_at": d.next_poll_at,
           "required_elements_ok": d.required_elements_ok, "verified_ownership": d.verified_ownership,
           "metrics": m.last_metrics, "money": a, "hook_id": d.hook_id,
           "held_snapshots": db.query(ViewSnapshot).filter_by(deliverable_id=d.id, anomaly="held").count(),
           "dispute": None}
    disp = db.query(Dispute).filter_by(deliverable_id=d.id).order_by(Dispute.created_at.desc()).first()
    if disp:
        out["dispute"] = {"id": disp.id, "reason": disp.reason, "evidence": disp.evidence,
                          "creator_response": disp.creator_response, "ops_decision": disp.ops_decision,
                          "created_at": disp.created_at, "decided_at": disp.decided_at}
    if with_snaps:
        out["snapshots"] = [snapshot(s) for s in db.query(ViewSnapshot).filter_by(deliverable_id=d.id)
                            .order_by(ViewSnapshot.polled_at).all()]
    return out


def hire(db: Session, h: Hire) -> dict:
    b = db.get(Brief, h.brief_id)
    c = db.query(Contract).filter_by(hire_id=h.id).order_by(Contract.version.desc()).first()
    cp = db.get(CreatorProfile, h.creator_id)
    return {"id": h.id, "status": h.status, "reserved_paise": h.reserved_paise, "created_at": h.created_at,
            "brief": brief(db, b, full=False), "creator": creator_card(db, cp),
            "contract": {"id": c.id, "version": c.version, "terms": c.terms, "usage_rights": c.usage_rights,
                         "creator_accepted_at": c.creator_accepted_at, "brand_accepted_at": c.brand_accepted_at} if c else None,
            "deliverables": [deliverable(db, d) for d in db.query(Deliverable).filter_by(hire_id=h.id)
                             .order_by(Deliverable.submitted_at).all()],
            "deliverables_expected": b.deliverables_per_creator}


def payout(db: Session, p: Payout) -> dict:
    d = db.get(Deliverable, p.deliverable_id)
    b = db.get(Brief, db.get(Hire, d.hire_id).brief_id)
    return {"id": p.id, "brief_title": b.title, "deliverable_id": p.deliverable_id, "gross_paise": p.amount_paise,
            "fee_paise": p.fee_paise, "gst_paise": p.gst_paise, "tds_paise": p.tds_paise, "net_paise": p.net_paise,
            "status": p.status, "hold_reason": p.hold_reason, "utr": p.utr, "invoice_no": p.invoice_no,
            "created_at": p.created_at, "settle_after": p.settle_after, "processed_at": p.processed_at}
