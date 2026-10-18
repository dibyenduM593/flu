from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func

from .. import serializers as S
from ..clock import now
from ..config import NICHES, TIER_ORDER
from ..deps import Principal, assert_org_member, brand, idempotency_key, remember, replay_or_none
from ..errors import ApiError, bad, not_found
from ..models import (AiJob, Application, Brief, CreatorProfile, Deliverable, Hire, LedgerEntry, Org, OrgMember, Payment,
                      Payout, PlatformAccount, User, ViewLedger)
from ..services import ai, briefs, matching, money
from ..services.audit import IST, latest_audit
from ..services.ops import audit

router = APIRouter(prefix="/v1", tags=["brand"])


def _org(p: Principal, org_id: str, roles=("owner", "admin", "member")) -> Org:
    assert_org_member(p.db, p.id, org_id, roles)
    org = p.db.get(Org, org_id)
    if not org:
        raise not_found("workspace")
    return org


def _brief(p: Principal, brief_id: str) -> tuple[Brief, Org]:
    b = p.db.get(Brief, brief_id)
    if not b:
        raise not_found("brief")
    return b, _org(p, b.org_id)


def _org_public(o: Org) -> dict:
    return {"id": o.id, "name": o.name, "type": o.type, "plan": o.plan, "gstin": o.gstin, "category": o.category,
            "city": o.city, "website": o.website, "instagram_handle": o.instagram_handle, "description": o.description,
            "take_rate": money.take_rate(o)}


class OrgIn(BaseModel):
    name: str | None = None
    gstin: str | None = None
    pan: str | None = None
    category: str | None = None
    city: str | None = None
    website: str | None = None
    instagram_handle: str | None = None
    description: str | None = None
    type: str | None = None
    plan: str | None = None


@router.post("/orgs")
def create_org(body: OrgIn, p: Principal = Depends(brand)):
    if not body.name:
        raise bad("name_required", "add your brand name")
    org = Org(name=body.name.strip(), gstin=(body.gstin or "").upper() or None, pan=(body.pan or "").upper() or None,
              category=body.category, city=body.city, website=body.website,
              instagram_handle=(body.instagram_handle or "").lstrip("@").lower() or None, description=body.description,
              type=body.type or "brand", created_by=p.id)
    p.db.add(org)
    p.db.flush()
    p.db.add(OrgMember(org_id=org.id, user_id=p.id, role="owner"))
    money.wallet(p.db, org.id)
    audit(p.db, p.id, "org.created", "org", org.id)
    p.db.commit()
    return _org_public(org)


@router.get("/orgs/{org_id}")
def get_org(org_id: str, p: Principal = Depends(brand)):
    return _org_public(_org(p, org_id))


@router.patch("/orgs/{org_id}")
def update_org(org_id: str, body: OrgIn, p: Principal = Depends(brand)):
    org = _org(p, org_id, ("owner", "admin"))
    for k, v in body.model_dump(exclude_none=True).items():
        if k == "plan" and v not in ("starter", "growth", "scale"):
            raise bad("invalid_plan", "plan is starter, growth or scale")
        if k == "instagram_handle":
            v = v.lstrip("@").lower()
        if k in ("gstin", "pan"):
            v = v.upper()
        setattr(org, k, v)
    p.db.commit()
    return _org_public(org)


class MemberIn(BaseModel):
    phone: str
    role: str = "member"


@router.post("/orgs/{org_id}/members")
def add_member(org_id: str, body: MemberIn, p: Principal = Depends(brand)):
    from ..services.identity import normalize_phone
    _org(p, org_id, ("owner",))
    phone = normalize_phone(body.phone)
    u = p.db.query(User).filter_by(phone=phone).first()
    if u and u.role != "brand_member":
        raise bad("not_brand_user", "that number belongs to a creator account")
    if not u:
        u = User(phone=phone, role="brand_member")
        p.db.add(u)
        p.db.flush()
    if not p.db.get(OrgMember, (org_id, u.id)):
        p.db.add(OrgMember(org_id=org_id, user_id=u.id, role=body.role if body.role in ("admin", "member") else "member"))
    p.db.commit()
    return {"ok": True}


@router.get("/orgs/{org_id}/members")
def members(org_id: str, p: Principal = Depends(brand)):
    _org(p, org_id)
    return {"data": [{"user_id": m.user_id, "role": m.role, "phone": p.db.get(User, m.user_id).phone[:-6] + "••••"
                      + p.db.get(User, m.user_id).phone[-2:]} for m in p.db.query(OrgMember).filter_by(org_id=org_id).all()]}


# ------------------------------------------------------------------ briefs
class DraftIn(BaseModel):
    product: str
    product_name: str | None = None
    goal: str = "awareness"
    budget_paise: int
    platforms: list[str] = ["instagram"]
    niches: list[str] = []
    tone: str | None = None
    notes: str | None = None


@router.post("/orgs/{org_id}/briefs/draft")
def draft(org_id: str, body: DraftIn, p: Principal = Depends(brand)):
    org = _org(p, org_id)
    if body.budget_paise < 10_000_00:
        raise bad("budget_too_small", "set a budget of at least ₹10,000")
    inp = {**body.model_dump(), "brand": org.name, "brand_handle": f"@{org.instagram_handle}" if org.instagram_handle else None,
           "category": org.category, "niches": [n for n in body.niches if n in NICHES]}
    job = ai.schedule(p.db, "trend_brief", inp, p.id)
    p.db.commit()
    return {"job_id": job.id, "status": job.status}


class BriefIn(BaseModel):
    title: str | None = None
    product: str | None = None
    goal: str | None = None
    platforms: list[str] | None = None
    deliverable_type: str | None = None
    deliverables_per_creator: int | None = None
    required_elements: dict | None = None
    dos: list[str] | None = None
    donts: list[str] | None = None
    pay_model: str | None = None
    cpm_paise: int | None = None
    flat_paise: int | None = None
    cap_paise: int | None = None
    min_tier: str | None = None
    niches: list[str] | None = None
    cities: list[str] | None = None
    max_creators: int | None = None
    deadline: datetime | None = None
    usage_rights: str | None = None
    tracking_days: int | None = None
    angles: list[dict] | None = None
    ai_draft_id: str | None = None


@router.post("/orgs/{org_id}/briefs")
def create_brief(org_id: str, body: BriefIn, p: Principal = Depends(brand)):
    org = _org(p, org_id)
    data = body.model_dump()
    if data.get("niches"):
        data["niches"] = [n for n in data["niches"] if n in NICHES]
    b = briefs.upsert(p.db, org, data, p.id)
    p.db.commit()
    return S.brief(p.db, b, org)


@router.get("/orgs/{org_id}/briefs")
def list_briefs(org_id: str, p: Principal = Depends(brand)):
    org = _org(p, org_id)
    rows = p.db.query(Brief).filter_by(org_id=org_id).order_by(Brief.created_at.desc()).all()
    out = []
    for b in rows:
        x = S.brief(p.db, b, org, full=False)
        x["performance"] = _perf_totals(p, b)
        out.append(x)
    return {"data": out}


@router.patch("/briefs/{brief_id}")
def update_brief(brief_id: str, body: BriefIn, p: Principal = Depends(brand)):
    b, org = _brief(p, brief_id)
    briefs.upsert(p.db, org, body.model_dump(exclude_none=True), p.id, brief=b)
    p.db.commit()
    return S.brief(p.db, b, org)


@router.post("/briefs/{brief_id}/publish")
def publish(brief_id: str, p: Principal = Depends(brand)):
    b, org = _brief(p, brief_id)
    briefs.publish(p.db, b, org, p.id)
    return S.brief(p.db, b, org)


class StatusIn(BaseModel):
    status: str


@router.post("/briefs/{brief_id}/status")
def brief_status(brief_id: str, body: StatusIn, p: Principal = Depends(brand)):
    b, org = _brief(p, brief_id)
    briefs.set_status(p.db, b, body.status, p.id)
    return S.brief(p.db, b, org)


def _applicant(p: Principal, a: Application) -> dict:
    cp = p.db.get(CreatorProfile, a.creator_id)
    accs = p.db.query(PlatformAccount).filter_by(creator_id=cp.user_id, status="active").all()
    audits = []
    for acc in accs:
        au = latest_audit(p.db, acc.id)
        if au:
            m = au.metrics
            audits.append({"platform": acc.platform, "handle": acc.handle, "followers": acc.follower_count,
                           "median_views": m["median_views"], "engagement_rate": m["engagement_rate"],
                           "reach_ratio": m["reach_ratio"], "posts_per_week": m["posts_per_week"], "result": au.result})
    hist = a.rank_breakdown.get("history", {})
    return {"id": a.id, "status": a.status, "pitch": a.pitch, "sample_url": a.sample_url, "invited": a.invited,
            "created_at": a.created_at, "rank_score": a.rank_score, "rank_breakdown": a.rank_breakdown,
            "creator": S.creator_card(p.db, cp), "audits": audits, "history": hist,
            "niche_fit": a.rank_breakdown.get("parts", {}).get("niche"),
            "sample_posts": matching.sample_posts(p.db, cp.user_id)}


@router.get("/briefs/{brief_id}/applications")
def applications(brief_id: str, sort: str = "rank", p: Principal = Depends(brand)):
    b, _ = _brief(p, brief_id)
    rows = p.db.query(Application).filter_by(brief_id=b.id).all()
    for a in rows:
        if a.status in ("applied", "shortlisted"):
            a.rank_score, a.rank_breakdown = matching.rank(p.db, a)  # scores move; re-rank on read
    p.db.commit()
    rows.sort(key=(lambda a: -a.rank_score) if sort == "rank" else (lambda a: a.created_at))
    return {"data": [_applicant(p, a) for a in rows]}


def _app_for_brand(p: Principal, app_id: str) -> tuple[Application, Brief, Org]:
    a = p.db.get(Application, app_id)
    if not a:
        raise not_found("application")
    b, org = _brief(p, a.brief_id)
    return a, b, org


@router.post("/applications/{app_id}/shortlist")
def shortlist(app_id: str, p: Principal = Depends(brand)):
    a, _, _ = _app_for_brand(p, app_id)
    if a.status == "applied":
        a.status = "shortlisted"
        p.db.commit()
    return {"id": a.id, "status": a.status}


@router.post("/applications/{app_id}/accept")
def accept(app_id: str, request: Request, key: str = Depends(idempotency_key), p: Principal = Depends(brand)):
    prior = replay_or_none(p.db, key, p.id, request)
    if prior:
        return prior
    a, b, org = _app_for_brand(p, app_id)
    h = briefs.accept(p.db, a, org, p.id)
    out = {"hire_id": h.id, "reserved_paise": h.reserved_paise, "application_id": a.id}
    remember(p.db, key, p.id, request, out)
    p.db.commit()
    return out


class TopNIn(BaseModel):
    n: int


@router.post("/briefs/{brief_id}/accept-top")
def accept_top(brief_id: str, body: TopNIn, request: Request, key: str = Depends(idempotency_key),
               p: Principal = Depends(brand)):
    prior = replay_or_none(p.db, key, p.id, request)
    if prior:
        return prior
    b, org = _brief(p, brief_id)
    rows = [a for a in p.db.query(Application).filter_by(brief_id=b.id).all() if a.status in ("applied", "shortlisted")]
    for a in rows:
        a.rank_score, a.rank_breakdown = matching.rank(p.db, a)
    rows.sort(key=lambda a: -a.rank_score)
    hired, errors = [], []
    for a in rows[:max(0, body.n)]:
        try:
            hired.append(briefs.accept(p.db, a, org, p.id).id)
        except ApiError as e:
            errors.append({"application_id": a.id, "code": e.code, "message": e.message})
            p.db.rollback()
            break
    out = {"hired": hired, "errors": errors}
    remember(p.db, key, p.id, request, out)
    p.db.commit()
    return out


@router.post("/applications/{app_id}/reject")
def reject(app_id: str, p: Principal = Depends(brand)):
    a, _, _ = _app_for_brand(p, app_id)
    briefs.reject(p.db, a, p.id)
    return {"id": a.id, "status": a.status}


class InviteIn(BaseModel):
    creator_ids: list[str]


@router.post("/briefs/{brief_id}/invites")
def invites(brief_id: str, body: InviteIn, p: Principal = Depends(brand)):
    b, org = _brief(p, brief_id)
    return {"invited": briefs.invite(p.db, b, org, body.creator_ids)}


@router.get("/briefs/{brief_id}/hires")
def hires(brief_id: str, p: Principal = Depends(brand)):
    b, _ = _brief(p, brief_id)
    return {"data": [S.hire(p.db, h) for h in p.db.query(Hire).filter_by(brief_id=b.id).order_by(Hire.created_at).all()]}


@router.post("/hires/{hire_id}/cancel")
def cancel(hire_id: str, p: Principal = Depends(brand)):
    h = p.db.get(Hire, hire_id)
    if not h:
        raise not_found("hire")
    _brief(p, h.brief_id)
    briefs.cancel_hire(p.db, h, p.id)
    return {"ok": True}


class ApproveIn(BaseModel):
    rating: dict | None = None


@router.post("/deliverables/{d_id}/approve")
def approve(d_id: str, request: Request, body: ApproveIn | None = None, key: str = Depends(idempotency_key),
            p: Principal = Depends(brand)):
    prior = replay_or_none(p.db, key, p.id, request)
    if prior:
        return prior
    d = p.db.get(Deliverable, d_id)
    if not d:
        raise not_found("deliverable")
    b = p.db.get(Brief, p.db.get(Hire, d.hire_id).brief_id)
    _org(p, b.org_id)
    briefs.approve(p.db, d_id, b.org_id, p.id, body.rating if body else None)
    out = S.deliverable(p.db, p.db.get(Deliverable, d_id))
    remember(p.db, key, p.id, request, {"id": d_id, "status": out["status"]})
    p.db.commit()
    return out


class DisputeIn(BaseModel):
    reason: str
    evidence_urls: list[str] = []


@router.post("/deliverables/{d_id}/dispute")
def dispute(d_id: str, body: DisputeIn, p: Principal = Depends(brand)):
    d = p.db.get(Deliverable, d_id)
    if not d:
        raise not_found("deliverable")
    b = p.db.get(Brief, p.db.get(Hire, d.hire_id).brief_id)
    _org(p, b.org_id)
    disp = briefs.dispute(p.db, d_id, b.org_id, p.id, body.reason, body.evidence_urls)
    return {"dispute_id": disp.id, "status": "disputed"}


# ------------------------------------------------------------------ performance
def _perf_totals(p: Principal, b: Brief) -> dict:
    views = cost = 0
    eng = 0
    for h in p.db.query(Hire).filter_by(brief_id=b.id).all():
        for d in p.db.query(Deliverable).filter_by(hire_id=h.id).all():
            a = money.accrued(p.db, d, b)
            views += a["verified_views"]
            cost += a["accrued_paise"]
    return {"verified_views": views, "cost_paise": cost, "cpm_paise": int(cost * 1000 / views) if views else None}


@router.get("/briefs/{brief_id}/performance")
def performance(brief_id: str, p: Principal = Depends(brand)):
    b, org = _brief(p, brief_id)
    rows, daily = [], defaultdict(int)
    total_views = total_cost = total_proj = 0
    for h in p.db.query(Hire).filter_by(brief_id=b.id).all():
        cp = p.db.get(CreatorProfile, h.creator_id)
        ee = matching.expected_earnings(p.db, cp.user_id, b)
        for d in p.db.query(Deliverable).filter_by(hire_id=h.id).all():
            x = S.deliverable(p.db, d)
            a = x["money"]
            m = x["metrics"] or {}
            e = sum(m.get(k, 0) for k in ("likes", "comments", "saves", "shares"))
            proj = a["accrued_paise"] if d.tracking_status != "tracking" else max(a["accrued_paise"], ee["per_deliverable_paise"])
            rows.append({"creator": S.creator_card(p.db, cp), "deliverable": x, "verified_views": a["verified_views"],
                         "engagement": e, "engagement_rate": round(e / max(m.get("reach", 1), 1), 4),
                         "cost_paise": a["accrued_paise"], "projected_paise": proj,
                         "cpm_paise": int(a["accrued_paise"] * 1000 / a["verified_views"]) if a["verified_views"] else None})
            total_views += a["verified_views"]
            total_cost += a["accrued_paise"]
            total_proj += proj
            for vl in p.db.query(ViewLedger).filter_by(deliverable_id=d.id, verified=True).all():
                daily[vl.created_at.astimezone(IST).date().isoformat()] += vl.delta_views
    days = sorted(daily)
    return {"brief": S.brief(p.db, b, org, full=False), "rows": rows,
            "totals": {"verified_views": total_views, "cost_paise": total_cost, "projected_paise": total_proj,
                       "cpm_paise": int(total_cost * 1000 / total_views) if total_views else None,
                       "deliverables": len(rows)},
            "daily": [{"date": d, "views": daily[d]} for d in days]}


@router.get("/orgs/{org_id}/overview")
def overview(org_id: str, p: Principal = Depends(brand)):
    org = _org(p, org_id)
    bs = p.db.query(Brief).filter_by(org_id=org_id).all()
    t = now()
    daily = defaultdict(int)
    views = cost = 0
    pending = []
    for b in bs:
        for h in p.db.query(Hire).filter_by(brief_id=b.id).all():
            for d in p.db.query(Deliverable).filter_by(hire_id=h.id).all():
                a = money.accrued(p.db, d, b)
                views += a["verified_views"]
                cost += a["accrued_paise"]
                if d.status == "submitted":
                    pending.append({"deliverable_id": d.id, "brief_id": b.id, "brief_title": b.title,
                                    "creator": p.db.get(CreatorProfile, h.creator_id).display_name,
                                    "deadline": d.approval_deadline_at})
                for vl in p.db.query(ViewLedger).filter(ViewLedger.deliverable_id == d.id, ViewLedger.verified.is_(True),
                                                        ViewLedger.created_at >= t - timedelta(days=14)).all():
                    daily[vl.created_at.astimezone(IST).date().isoformat()] += vl.delta_views
    series = []
    for i in range(13, -1, -1):
        day = (t - timedelta(days=i)).astimezone(IST).date().isoformat()
        series.append({"date": day, "views": daily.get(day, 0)})
    apps_new = (p.db.query(Application).join(Brief, Brief.id == Application.brief_id)
                .filter(Brief.org_id == org_id, Application.status == "applied").count())
    return {"org": _org_public(org), "wallet": money.summary(p.db, org_id),
            "kpis": {"live_briefs": sum(1 for b in bs if b.status == "live"), "verified_views": views,
                     "cost_paise": cost, "cpm_paise": int(cost * 1000 / views) if views else None,
                     "new_applications": apps_new, "pending_approvals": len(pending)},
            "pending_approvals": sorted(pending, key=lambda x: x["deadline"]), "daily": series}


# ------------------------------------------------------------------ wallet
@router.get("/orgs/{org_id}/wallet")
def get_wallet(org_id: str, p: Principal = Depends(brand)):
    _org(p, org_id)
    entries = (p.db.query(LedgerEntry).filter_by(wallet_id=org_id).order_by(LedgerEntry.created_at.desc()).limit(200).all())
    pays = p.db.query(Payment).filter_by(org_id=org_id).order_by(Payment.created_at.desc()).all()
    return {"summary": money.summary(p.db, org_id),
            "entries": [{"id": e.id, "kind": e.kind, "amount_paise": e.amount_paise, "ref_type": e.ref_type,
                         "ref_id": e.ref_id, "memo": e.memo, "created_at": e.created_at} for e in entries],
            "payments": [{"id": x.id, "order_id": x.rzp_order_id, "payment_id": x.rzp_payment_id,
                          "amount_paise": x.amount_paise, "status": x.status, "created_at": x.created_at,
                          "captured_at": x.captured_at} for x in pays]}


class TopupIn(BaseModel):
    amount_paise: int


@router.post("/orgs/{org_id}/wallet/topup")
def topup(org_id: str, body: TopupIn, request: Request, key: str = Depends(idempotency_key), p: Principal = Depends(brand)):
    prior = replay_or_none(p.db, key, p.id, request)
    if prior:
        return prior
    org = _org(p, org_id, ("owner", "admin"))
    out = money.create_topup(p.db, org, body.amount_paise, p.id)
    remember(p.db, key, p.id, request, out)
    p.db.commit()
    return out


class VerifyIn(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


@router.post("/orgs/{org_id}/wallet/verify")
def verify(org_id: str, body: VerifyIn, p: Principal = Depends(brand)):
    _org(p, org_id)
    money.verify_checkout(p.db, body.razorpay_order_id, body.razorpay_payment_id, body.razorpay_signature)
    return {"verified": True, "wallet": money.summary(p.db, org_id)}


class RefundIn(BaseModel):
    payment_id: str
    amount_paise: int


@router.post("/orgs/{org_id}/wallet/refund")
def refund(org_id: str, body: RefundIn, p: Principal = Depends(brand)):
    org = _org(p, org_id, ("owner",))
    return money.refund(p.db, org, body.payment_id, body.amount_paise, p.id)


@router.get("/orgs/{org_id}/payouts")
def org_payouts(org_id: str, p: Principal = Depends(brand)):
    _org(p, org_id)
    rows = p.db.query(Payout).filter_by(org_id=org_id).order_by(Payout.created_at.desc()).all()
    out = []
    for x in rows:
        d = S.payout(p.db, x)
        d["creator"] = p.db.get(CreatorProfile, x.creator_id).display_name
        out.append(d)
    return {"data": out}


@router.get("/orgs/{org_id}/payouts/export")
def export(org_id: str, p: Principal = Depends(brand), **kw):
    _org(p, org_id)
    csv_text = money.payouts_csv(p.db, org_id, None, None)
    return Response(csv_text, media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="flu-payouts-{now().date()}.csv"'})


# ------------------------------------------------------------------ directory + trends
@router.get("/directory/creators")
def directory(niche: str | None = None, tier: str | None = None, city: str | None = None, q: str | None = None,
              platform: str | None = None, p: Principal = Depends(brand)):
    out = []
    for cp in p.db.query(CreatorProfile).filter_by(eligible=True).all():
        if niche and niche not in (cp.niches or []):
            continue
        if tier and TIER_ORDER.get(cp.tier, 0) < TIER_ORDER.get(tier, 0):
            continue
        if city and cp.city != city:
            continue
        accs = p.db.query(PlatformAccount).filter_by(creator_id=cp.user_id, status="active").all()
        if platform and platform not in {a.platform for a in accs}:
            continue
        if q and q.lower() not in cp.display_name.lower() and not any(q.lower() in a.handle for a in accs):
            continue
        mv = matching.median_views(p.db, cp.user_id, [platform] if platform else ["instagram", "youtube"])
        out.append({**S.creator_card(p.db, cp), "median_views": mv, "sample_posts": matching.sample_posts(p.db, cp.user_id),
                    "flu_history": matching.flu_history(p.db, cp.user_id)})
    out.sort(key=lambda c: -c["score"])
    return {"data": out}


@router.get("/trends")
def trends(niche: str | None = None, p: Principal = Depends(brand)):
    return {"data": ai.trend_corpus(p.db, [niche] if niche else []), "priors": ai.pricing_priors(p.db, [])}
