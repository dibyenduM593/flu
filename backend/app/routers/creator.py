from datetime import timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func

from .. import serializers as S
from ..clock import now
from ..config import NICHES, TIER_ORDER
from ..deps import Principal, creator, current
from ..errors import ApiError, bad, forbidden, not_found
from ..models import (AiJob, Application, Brief, CreatorProfile, Deliverable, Dispute, Hire, HookIssued, KycRecord,
                      MediaItem, Org, PlatformAccount, Payout, ScoreRun)
from ..services import ai, briefs, kyc, matching, money, scoring
from ..services.audit import IST, latest_audit
from ..services.connections import access_token
from .. import providers

router = APIRouter(prefix="/v1", tags=["creator"])


class ProfileIn(BaseModel):
    display_name: str = Field(min_length=2, max_length=120)
    city: str | None = None
    state: str | None = None
    bio: str | None = None


@router.post("/creator/profile")
def create_profile(body: ProfileIn, p: Principal = Depends(current)):
    if p.role != "creator":
        raise forbidden("creator scope required")
    cp = p.db.get(CreatorProfile, p.id) or CreatorProfile(user_id=p.id, display_name=body.display_name)
    cp.display_name, cp.city, cp.state, cp.bio = body.display_name, body.city, body.state, body.bio
    p.db.add(cp)
    p.db.commit()
    return S.creator_card(p.db, cp)


class NichesIn(BaseModel):
    niches: list[str]


@router.patch("/creator/niches")
def confirm_niches(body: NichesIn, p: Principal = Depends(creator)):
    ns = [n for n in body.niches if n in NICHES][:3]
    if not ns:
        raise bad("invalid_niches", "pick 1 to 3 niches from the list")
    cp = p.db.get(CreatorProfile, p.id)
    cp.niches, cp.niches_confirmed = ns, True
    scoring.run_score(p.db, p.id, trigger="niches")
    p.db.commit()
    return {"niches": cp.niches}


def _brief_feed(p: Principal, niche: str | None = None, pay_model: str | None = None):
    cp = p.db.get(CreatorProfile, p.id)
    eligible, locked = [], []
    applied = {a.brief_id: a.status for a in p.db.query(Application).filter_by(creator_id=p.id).all()}
    for b in p.db.query(Brief).filter_by(status="live").all():
        if niche and niche not in (b.niches or []):
            continue
        if pay_model and b.pay_model != pay_model:
            continue
        ok, reasons = matching.eligibility(p.db, cp, b)
        item = {**S.brief(p.db, b, full=False), "expected": matching.expected_earnings(p.db, p.id, b),
                "application_status": applied.get(b.id)}
        if ok:
            eligible.append(item)
        else:
            locked.append({**item, "locked_reasons": reasons})
    eligible.sort(key=lambda x: -x["expected"]["total_paise"])
    locked.sort(key=lambda x: (len(x["locked_reasons"]), -x["expected"]["total_paise"]))
    return eligible, locked


@router.get("/creator/home")
def home(p: Principal = Depends(creator)):
    db = p.db
    cp = db.get(CreatorProfile, p.id)
    accs = db.query(PlatformAccount).filter_by(creator_id=p.id).all()
    eligible, locked = _brief_feed(p)
    nt, floor = scoring.next_tier(float(cp.score))
    hires = db.query(Hire).filter_by(creator_id=p.id, status="active").all()
    pays = db.query(Payout).filter_by(creator_id=p.id).all()
    accrued_unreleased = 0
    for h in db.query(Hire).filter_by(creator_id=p.id).all():
        for d in db.query(Deliverable).filter_by(hire_id=h.id).all():
            accrued_unreleased += money.accrued(db, d)["unreleased_paise"]
    last = None
    ids = [a.id for a in accs if a.status == "active"]
    if ids:
        m = db.query(MediaItem).filter(MediaItem.platform_account_id.in_(ids)).order_by(MediaItem.posted_at.desc()).first()
        if m:
            last = {"id": m.id, "caption": (m.caption or "")[:90], "posted_at": m.posted_at, "metrics": m.last_metrics,
                    "permalink": m.permalink}
    audits = {a.platform: (latest_audit(db, a.id).result if latest_audit(db, a.id) else None) for a in accs}
    history = [{"run_at": r.run_at, "score": float(r.score), "tier": r.tier} for r in
               db.query(ScoreRun).filter_by(creator_id=p.id).order_by(ScoreRun.run_at).all()][-20:]
    return {
        "profile": S.creator_card(db, cp), "score": float(cp.score), "tier": cp.tier, "next_tier": nt,
        "points_to_next_tier": round(floor - float(cp.score), 1) if floor else None,
        "streak_weeks": cp.streak_weeks, "points": cp.points,
        "qualifying_briefs": len(eligible), "top_briefs": eligible[:3], "locked_briefs": locked[:3],
        "locked_count": len(locked), "active_hires": len(hires), "last_post": last, "score_history": history,
        "earnings": {"accrued_paise": accrued_unreleased,
                     "settling_paise": sum(x.net_paise for x in pays if x.status == "processing"),
                     "held_kyc_paise": sum(x.amount_paise for x in pays if x.status == "queued"),
                     "paid_paise": sum(x.net_paise for x in pays if x.status == "processed")},
        "checklist": {"profile": True, "connected": any(a.status == "active" for a in accs),
                      "audit": any(v == "pass" for v in audits.values()), "audit_flagged": any(v == "flag" for v in audits.values()),
                      "niches_confirmed": cp.niches_confirmed, "kyc": cp.kyc_status == "verified"},
        "niches": cp.niches, "niche_confidence": cp.niche_confidence,
    }


@router.get("/creator/audit")
def get_audit(p: Principal = Depends(creator)):
    out = []
    for acc in p.db.query(PlatformAccount).filter_by(creator_id=p.id).all():
        a = latest_audit(p.db, acc.id)
        out.append({"account": {"id": acc.id, "platform": acc.platform, "handle": acc.handle, "status": acc.status},
                    "audit": a and {"run_at": a.run_at, "result": a.result, "fraud_flags": a.fraud_flags,
                                    "metrics": {k: v for k, v in a.metrics.items() if k != "views_per_reach"}}})
    return {"data": out}


@router.get("/creator/score")
def get_score(p: Principal = Depends(creator)):
    res = scoring.compute(p.db, p.id)
    if not res:
        raise ApiError(409, "no_audit", "connect an account to get your Creator Score")
    cp = p.db.get(CreatorProfile, p.id)
    # Use the stored score (which the tier is based on) as the headline; compute() is the live view.
    res["stored_score"], res["stored_tier"] = float(cp.score), cp.tier
    return res


@router.get("/creator/media")
def media(platform: str | None = None, p: Principal = Depends(creator)):
    q = p.db.query(PlatformAccount).filter_by(creator_id=p.id, status="active")
    if platform:
        q = q.filter_by(platform=platform)
    accs = {a.id: a for a in q.all()}
    if not accs:
        return {"data": []}
    rows = (p.db.query(MediaItem).filter(MediaItem.platform_account_id.in_(list(accs)))
            .order_by(MediaItem.posted_at.desc()).limit(60).all())
    diag = {j.input.get("media_item_id"): j.id for j in p.db.query(AiJob).filter_by(created_by=p.id, kind="diagnosis").all()}
    used = {d.media_item_id for d in p.db.query(Deliverable).all()}
    return {"data": [{"id": m.id, "platform": accs[m.platform_account_id].platform, "permalink": m.permalink,
                      "caption": m.caption, "posted_at": m.posted_at, "duration_s": m.duration_s,
                      "metrics": m.last_metrics, "diagnosis_job_id": diag.get(m.id), "is_deliverable": m.id in used}
                     for m in rows]}


@router.post("/creator/media/{media_id}/diagnose")
def diagnose(media_id: str, p: Principal = Depends(creator)):
    m = p.db.get(MediaItem, media_id)
    if not m or p.db.get(PlatformAccount, m.platform_account_id).creator_id != p.id:
        raise not_found("media")
    job = ai.schedule(p.db, "diagnosis", {"media_item_id": m.id}, p.id)
    p.db.commit()
    return {"job_id": job.id, "status": job.status}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, p: Principal = Depends(current)):
    j = p.db.get(AiJob, job_id)
    if not j or (j.created_by != p.id and p.role != "ops"):
        raise not_found("job")
    return ai.public_job(j)


class FeedbackIn(BaseModel):
    feedback: str


@router.post("/jobs/{job_id}/feedback")
def job_feedback(job_id: str, body: FeedbackIn, p: Principal = Depends(current)):
    j = p.db.get(AiJob, job_id)
    if not j or j.created_by != p.id:
        raise not_found("job")
    if body.feedback not in ("up", "down"):
        raise bad("invalid_feedback", "feedback is up or down")
    j.feedback = body.feedback
    p.db.commit()
    return {"ok": True}


class HooksIn(BaseModel):
    brief_id: str | None = None
    niche: str | None = None
    product: str | None = None


def _hook(h: HookIssued) -> dict:
    return {"id": h.id, "pattern": h.pattern, "first_line": h.first_line, "on_screen_text": h.on_screen_text,
            "why_it_fits": h.why_it_fits, "brief_id": h.brief_id, "used_media_id": h.used_media_id,
            "created_at": h.created_at}


@router.post("/creator/hooks")
def hooks(body: HooksIn, p: Principal = Depends(creator)):
    cp = p.db.get(CreatorProfile, p.id)
    niche = body.niche or (cp.niches[0] if cp.niches else "comedy")
    rows = ai.generate_hooks(p.db, p.id, niche, body.product, body.brief_id)
    p.db.commit()
    return {"hooks": [_hook(h) for h in rows]}


@router.get("/creator/hooks")
def hooks_list(brief_id: str | None = None, p: Principal = Depends(creator)):
    q = p.db.query(HookIssued).filter_by(creator_id=p.id)
    if brief_id:
        q = q.filter_by(brief_id=brief_id)
    return {"data": [_hook(h) for h in q.order_by(HookIssued.created_at.desc()).limit(30).all()]}


class HookUsedIn(BaseModel):
    media_item_id: str


@router.post("/creator/hooks/{hook_id}/used")
def hook_used(hook_id: str, body: HookUsedIn, p: Principal = Depends(creator)):
    h = p.db.get(HookIssued, hook_id)
    m = p.db.get(MediaItem, body.media_item_id)
    if not h or h.creator_id != p.id or not m or p.db.get(PlatformAccount, m.platform_account_id).creator_id != p.id:
        raise not_found("hook")
    h.used_media_id = m.id
    p.db.commit()
    return _hook(h)


@router.get("/creator/schedule")
def schedule(p: Principal = Depends(creator)):
    """CA-5: online_followers (where available) blended with your own best-performing hours, in IST."""
    acc = scoring.primary_account(p.db, p.id)
    if not acc:
        raise ApiError(409, "no_account", "connect an account first")
    a = latest_audit(p.db, acc.id)
    best = a.metrics.get("best_hours_ist", []) if a else []
    online = None
    try:
        online = providers.social_for(acc, p.db).online_followers(access_token(p.db, acc))
    except Exception:
        online = None
    hours = {}
    mx = max(online.values()) if online else 1
    for h in range(7, 24):
        o = (online.get(h, 0) / mx) if online else 0  # adapters normalise online_followers to IST hours
        perf = 1.0 if h in best[:1] else 0.7 if h in best else 0
        hours[h] = round(0.6 * o + 0.4 * perf if online else perf, 3)
    top = sorted(hours, key=lambda h: -hours[h])[:3]
    t = now().astimezone(IST)
    slots = []
    for i in range(7):
        day = (t + timedelta(days=i)).date()
        for h in top:
            slots.append({"date": day.isoformat(), "weekday": day.strftime("%A"), "hour_ist": h, "score": hours[h]})
    return {"top_hours_ist": top, "hour_scores": hours, "source": "online_followers + own posts" if online else "own posts only",
            "slots": slots[:9]}


@router.get("/creator/briefs")
def brief_feed(niche: str | None = None, pay_model: str | None = None, p: Principal = Depends(creator)):
    eligible, locked = _brief_feed(p, niche, pay_model)
    return {"data": eligible, "locked": locked}


@router.get("/briefs/{brief_id}")
def get_brief(brief_id: str, p: Principal = Depends(current)):
    b = p.db.get(Brief, brief_id)
    if not b:
        raise not_found("brief")
    if p.role == "creator":
        cp = p.db.get(CreatorProfile, p.id)
        if not cp:
            raise not_found("brief")
        ok, reasons = matching.eligibility(p.db, cp, b)
        app = p.db.query(Application).filter_by(brief_id=b.id, creator_id=p.id).first()
        if b.status != "live" and not app:
            raise not_found("brief")
        return {**S.brief(p.db, b), "eligible": ok, "locked_reasons": reasons,
                "expected": matching.expected_earnings(p.db, p.id, b),
                "application": app and {"id": app.id, "status": app.status, "pitch": app.pitch}}
    from ..deps import assert_org_member
    assert_org_member(p.db, p.id, b.org_id)
    return S.brief(p.db, b)


class ApplyIn(BaseModel):
    pitch: str
    sample_url: str | None = None


@router.post("/briefs/{brief_id}/applications")
def apply(brief_id: str, body: ApplyIn, p: Principal = Depends(creator)):
    b = p.db.get(Brief, brief_id)
    if not b:
        raise not_found("brief")
    app = briefs.apply(p.db, p.db.get(CreatorProfile, p.id), b, body.pitch, body.sample_url)
    return {"id": app.id, "status": app.status, "rank_score": app.rank_score}


@router.post("/applications/{app_id}/withdraw")
def withdraw(app_id: str, p: Principal = Depends(creator)):
    app = p.db.get(Application, app_id)
    if not app or app.creator_id != p.id:
        raise not_found("application")
    briefs.withdraw(p.db, app)
    return {"ok": True}


@router.get("/creator/applications")
def my_applications(p: Principal = Depends(creator)):
    rows = p.db.query(Application).filter_by(creator_id=p.id).order_by(Application.created_at.desc()).all()
    return {"data": [{"id": a.id, "status": a.status, "pitch": a.pitch, "created_at": a.created_at,
                      "invited": a.invited, "brief": S.brief(p.db, p.db.get(Brief, a.brief_id), full=False)} for a in rows]}


@router.get("/creator/hires")
def my_hires(p: Principal = Depends(creator)):
    rows = p.db.query(Hire).filter_by(creator_id=p.id).order_by(Hire.created_at.desc()).all()
    out = []
    for h in rows:
        x = S.hire(p.db, h)
        b = p.db.get(Brief, h.brief_id)
        x["brief_full"] = S.brief(p.db, b)
        out.append(x)
    return {"data": out}


@router.post("/hires/{hire_id}/contract/accept")
def contract_accept(hire_id: str, p: Principal = Depends(creator)):
    h = p.db.get(Hire, hire_id)
    if not h:
        raise not_found("hire")
    c = briefs.accept_contract(p.db, h, p.id)
    return {"id": c.id, "creator_accepted_at": c.creator_accepted_at}


class SubmitIn(BaseModel):
    post_url: str
    hook_id: str | None = None


@router.post("/hires/{hire_id}/deliverables")
def submit(hire_id: str, body: SubmitIn, p: Principal = Depends(creator)):
    h = p.db.get(Hire, hire_id)
    if not h:
        raise not_found("hire")
    d = briefs.submit(p.db, h, p.id, body.post_url, body.hook_id)
    return S.deliverable(p.db, d)


@router.get("/deliverables/{d_id}")
def get_deliverable(d_id: str, p: Principal = Depends(current)):
    d = p.db.get(Deliverable, d_id)
    if not d:
        raise not_found("deliverable")
    h = p.db.get(Hire, d.hire_id)
    if p.role == "creator" and h.creator_id != p.id:
        raise not_found("deliverable")
    if p.role == "brand_member":
        from ..deps import assert_org_member
        assert_org_member(p.db, p.id, p.db.get(Brief, h.brief_id).org_id)
    return S.deliverable(p.db, d, with_snaps=True)


class RespondIn(BaseModel):
    response: str


@router.post("/disputes/{dispute_id}/respond")
def dispute_respond(dispute_id: str, body: RespondIn, p: Principal = Depends(creator)):
    disp = p.db.get(Dispute, dispute_id)
    if not disp:
        raise not_found("dispute")
    briefs.respond_dispute(p.db, disp, p.id, body.response)
    return {"ok": True}


@router.get("/creator/earnings")
def earnings(p: Principal = Depends(creator)):
    db = p.db
    lines = []
    for h in db.query(Hire).filter_by(creator_id=p.id).all():
        b = db.get(Brief, h.brief_id)
        org = db.get(Org, b.org_id)
        for d in db.query(Deliverable).filter_by(hire_id=h.id).all():
            a = money.accrued(db, d, b)
            if a["unreleased_paise"]:
                lines.append({"kind": "accrued", "brief_title": b.title, "brand": org.name, "deliverable_id": d.id,
                              "gross_paise": a["unreleased_paise"], "status": d.status,
                              "verified_views": a["verified_views"], "at": d.submitted_at})
    pays = db.query(Payout).filter_by(creator_id=p.id).order_by(Payout.created_at.desc()).all()
    fy_gross = sum(x.amount_paise for x in pays if x.status in ("processing", "processed"))
    return {"lines": lines, "payouts": [S.payout(db, x) for x in pays],
            "totals": {"accrued_paise": sum(l["gross_paise"] for l in lines),
                       "held_kyc_paise": sum(x.amount_paise for x in pays if x.status == "queued"),
                       "settling_paise": sum(x.net_paise for x in pays if x.status == "processing"),
                       "paid_paise": sum(x.net_paise for x in pays if x.status == "processed"),
                       "tds_paise": sum(x.tds_paise for x in pays), "fy_gross_paise": fy_gross},
            "gst_warning": fy_gross >= 15_00_000_00,
            "kyc": kyc.public(db.get(KycRecord, p.id))}


class KycAddress(BaseModel):
    street1: str
    street2: str | None = None
    city: str
    state: str
    postal_code: str


class KycIn(BaseModel):
    pan: str
    name: str
    ifsc: str | None = None
    account_number: str | None = None
    vpa: str | None = None
    gstin: str | None = None
    # Razorpay Route needs both for the creator's linked account (live mode only).
    email: str | None = None
    address: KycAddress | None = None


@router.post("/creator/kyc")
def submit_kyc(body: KycIn, p: Principal = Depends(creator)):
    if not body.vpa and not (body.ifsc and body.account_number):
        raise bad("payout_method_required", "add a bank account (IFSC + number) or a UPI ID")
    rec = kyc.submit(p.db, p.db.get(CreatorProfile, p.id), body.pan, body.name, body.ifsc, body.account_number,
                     body.vpa, body.gstin, body.email, body.address.model_dump() if body.address else None)
    return kyc.public(rec)


@router.get("/creator/kyc")
def get_kyc(p: Principal = Depends(creator)):
    return kyc.public(p.db.get(KycRecord, p.id))


@router.post("/creator/withdraw")
def withdraw_funds(p: Principal = Depends(creator)):
    raise ApiError(409, "auto_release", "Under Razorpay Route your earnings are released automatically on approval; "
                                        "instant UPI withdrawals arrive with RazorpayX in V1.")
