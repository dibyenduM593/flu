from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import case, func

from .. import clock
from ..ai import registry
from ..deps import Principal, ops
from ..errors import bad, not_found
from ..models import (AccountAudit, AiJob, AuditLog, CreatorProfile, Deliverable, Dispute, Job, OpsItem,
                      PlatformAccount, SimState, ViewSnapshot)
from ..services import briefs, jobs, scoring, tracking
from ..services.audit import refresh_eligibility
from ..services.ops import resolve

router = APIRouter(prefix="/v1/ops", tags=["ops"])


def _item(db, i: OpsItem) -> dict:
    out = {"id": i.id, "type": i.type, "reason_code": i.reason_code, "entity_type": i.entity_type,
           "entity_id": i.entity_id, "summary": i.summary, "details": i.details, "status": i.status,
           "decision": i.decision, "note": i.note, "created_at": i.created_at, "resolved_at": i.resolved_at}
    if i.type == "dispute":
        d = db.get(Dispute, i.entity_id)
        if d:
            out["dispute"] = {"reason": d.reason, "evidence": d.evidence, "creator_response": d.creator_response,
                              "deliverable_id": d.deliverable_id, "created_at": d.created_at}
    if i.type == "view_anomaly":
        s = db.get(ViewSnapshot, i.entity_id)
        if s:
            out["snapshot"] = {"views": s.views, "likes": s.likes, "polled_at": s.polled_at, "anomaly": s.anomaly}
    return out


@router.get("/queue")
def queue(type: str | None = None, status: str = "open", p: Principal = Depends(ops)):
    q = p.db.query(OpsItem)
    if type:
        q = q.filter_by(type=type)
    if status != "all":
        q = q.filter_by(status=status)
    rows = q.order_by(OpsItem.created_at.desc()).limit(200).all()
    counts = dict(p.db.query(OpsItem.type, func.count()).filter_by(status="open").group_by(OpsItem.type).all())
    return {"data": [_item(p.db, i) for i in rows], "open_counts": counts}


class ResolveIn(BaseModel):
    decision: str
    note: str | None = None


@router.post("/queue/{item_id}/resolve")
def resolve_item(item_id: str, body: ResolveIn, p: Principal = Depends(ops)):
    db = p.db
    i = db.get(OpsItem, item_id)
    if not i:
        raise not_found("ops item")
    if i.status != "open":
        raise bad("already_resolved", "this item is already resolved")
    if i.type == "dispute":
        briefs.decide_dispute(db, db.get(Dispute, i.entity_id), body.decision, p.id, body.note)
    elif i.type == "view_anomaly":
        if body.decision not in ("cleared", "rejected"):
            raise bad("invalid_decision", "decision is cleared or rejected")
        tracking.clear_snapshot(db, db.get(ViewSnapshot, i.entity_id), body.decision)
    elif i.type == "fraud_flag" and i.entity_type == "platform_account":
        acc = db.get(PlatformAccount, i.entity_id)
        a = (db.query(AccountAudit).filter_by(platform_account_id=acc.id).order_by(AccountAudit.run_at.desc()).first())
        if body.decision == "cleared":
            a.result = "pass"
        elif body.decision == "rejected":
            a.result = "fail"
        else:
            raise bad("invalid_decision", "decision is cleared or rejected")
        refresh_eligibility(db, db.get(CreatorProfile, acc.creator_id))
    resolve(db, i, body.decision, body.note, p.id)
    db.commit()
    return _item(db, i)


@router.post("/snapshots/{snap_id}/clear")
def clear_snapshot(snap_id: str, p: Principal = Depends(ops)):
    s = p.db.get(ViewSnapshot, snap_id)
    if not s:
        raise not_found("snapshot")
    tracking.clear_snapshot(p.db, s, "cleared")
    for i in p.db.query(OpsItem).filter_by(entity_id=snap_id, status="open").all():
        resolve(p.db, i, "cleared", None, p.id)
    p.db.commit()
    return {"ok": True}


@router.post("/creators/{creator_id}/rescore")
def rescore(creator_id: str, p: Principal = Depends(ops)):
    res = scoring.run_score(p.db, creator_id, trigger="ops")
    p.db.commit()
    return res or {"score": None}


@router.get("/ai/evals")
def evals(p: Principal = Depends(ops)):
    stats = p.db.query(AiJob.kind, AiJob.model, func.count(), func.sum(AiJob.cost_paise), func.avg(AiJob.latency_ms),
                       func.sum(case((AiJob.feedback == "up", 1), else_=0)),
                       func.sum(case((AiJob.feedback == "down", 1), else_=0))) \
        .group_by(AiJob.kind, AiJob.model).all()
    return {"prompts": registry.all_prompts(),
            "usage": [{"kind": k, "model": m, "calls": n, "cost_paise": int(c or 0), "avg_latency_ms": int(l or 0),
                       "thumbs_up": int(u or 0), "thumbs_down": int(d or 0)} for k, m, n, c, l, u, d in stats]}


@router.get("/audit-log")
def audit_log(p: Principal = Depends(ops)):
    rows = p.db.query(AuditLog).order_by(AuditLog.at.desc()).limit(150).all()
    return {"data": [{"id": r.id, "actor_id": r.actor_id, "action": r.action, "entity_type": r.entity_type,
                      "entity_id": r.entity_id, "after": r.after, "at": r.at} for r in rows]}


@router.get("/system")
def system(p: Principal = Depends(ops)):
    db = p.db
    rec = db.get(SimState, "last_reconcile")
    return {"clock": {"now": clock.now(), "offset_hours": clock.offset_hours()},
            "jobs": dict(db.query(Job.status, func.count()).group_by(Job.status).all()),
            "next_jobs": [{"kind": j.kind, "run_at": j.run_at} for j in
                          db.query(Job).filter_by(status="queued").order_by(Job.run_at).limit(12).all()],
            "failed_jobs": [{"kind": j.kind, "error": (j.last_error or "")[:300], "at": j.finished_at} for j in
                            db.query(Job).filter_by(status="failed").order_by(Job.finished_at.desc()).limit(10).all()],
            "held_snapshots": db.query(ViewSnapshot).filter_by(anomaly="held").count(),
            "tracking": db.query(Deliverable).filter_by(tracking_status="tracking").count(),
            "deliverables": [_deliv_row(db, d) for d in db.query(Deliverable).order_by(Deliverable.submitted_at.desc()).limit(30).all()],
            "accounts": [{"id": a.id, "platform": a.platform, "handle": a.handle, "status": a.status}
                         for a in db.query(PlatformAccount).order_by(PlatformAccount.handle).all()],
            "last_reconcile": rec.value if rec else None}


def _deliv_row(db, d: Deliverable) -> dict:
    from ..models import Brief, Hire, MediaItem
    h = db.get(Hire, d.hire_id)
    m = db.get(MediaItem, d.media_item_id)
    return {"id": d.id, "brief": db.get(Brief, h.brief_id).title, "creator": db.get(CreatorProfile, h.creator_id).display_name,
            "status": d.status, "tracking_status": d.tracking_status, "views": (m.last_metrics or {}).get("views"),
            "next_poll_at": d.next_poll_at, "submitted_at": d.submitted_at}


@router.post("/reconcile")
def run_reconcile(p: Principal = Depends(ops)):
    from ..services.money import reconcile
    return reconcile(p.db)
