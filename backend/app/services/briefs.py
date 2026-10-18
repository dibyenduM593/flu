"""Briefs, applications, hires, contracts, deliverables, approvals and disputes (M3, TS-2)."""
from datetime import timedelta

from sqlalchemy.orm import Session

from .. import providers
from ..clock import now
from ..config import (APPROVAL_WINDOW_H, DISCLOSURE_TAGS, DISPUTE_RESPONSE_H, MAX_OPEN_APPLICATIONS,
                      PLAN_LIVE_CREATORS, TIER_ORDER)
from ..errors import ApiError, bad, conflict, forbidden, not_found
from ..models import (Application, Brief, BriefAngle, Contract, CreatorProfile, Deliverable, Dispute, Hire, HookIssued,
                      Invite, MediaItem, Org, OrgMember, PlatformAccount)
from . import jobs, matching, money, tracking
from .ops import audit, notify, open_item

BRIEF_FIELDS = ["title", "product", "goal", "platforms", "deliverable_type", "deliverables_per_creator",
                "required_elements", "dos", "donts", "pay_model", "cpm_paise", "flat_paise", "cap_paise", "min_tier",
                "niches", "cities", "max_creators", "deadline", "usage_rights", "tracking_days"]
USAGE = {"organic": "Organic only", "organic_paid_90d": "Organic + paid ads for 90 days", "paid_perpetual": "Paid, perpetual"}


def org_members(db: Session, org_id: str) -> list[str]:
    return [m.user_id for m in db.query(OrgMember).filter_by(org_id=org_id).all()]


# ------------------------------------------------------------------ briefs
def validate(b: Brief):
    if b.pay_model not in ("cpm", "flat", "hybrid"):
        raise bad("invalid_pay_model", "pay model must be cpm, flat or hybrid")
    if b.pay_model in ("cpm", "hybrid") and (b.cpm_paise <= 0 or b.cap_paise <= 0):
        raise bad("cpm_required", "CPM and cap are required for CPM and hybrid briefs")
    if b.pay_model in ("flat", "hybrid") and b.flat_paise <= 0:
        raise bad("flat_required", "a flat/base amount is required for flat and hybrid briefs")
    if b.pay_model == "hybrid" and b.cap_paise <= b.flat_paise:
        raise bad("cap_below_base", "the cap must be above the base amount")
    if not set(b.platforms) <= {"instagram", "youtube"} or not b.platforms:
        raise bad("invalid_platforms", "Instagram Reels and YouTube Shorts only")
    if b.min_tier not in TIER_ORDER:
        raise bad("invalid_tier", "unknown tier")
    if b.max_creators < 1 or b.deliverables_per_creator < 1:
        raise bad("invalid_counts", "counts must be at least 1")
    req = b.required_elements or {}
    tags = [h.lower() for h in req.get("hashtags", [])]
    if not req.get("disclosure", True) and not set(tags) & set(DISCLOSURE_TAGS):
        raise bad("disclosure_required", "ASCI requires a disclosure (#ad, #collab or paid-partnership label)")


def upsert(db: Session, org: Org, data: dict, actor: str, brief: Brief | None = None) -> Brief:
    if brief and brief.status not in ("draft", "paused"):
        raise conflict("brief_locked", "pause the brief before editing")
    b = brief or Brief(org_id=org.id, title=data.get("title") or "Untitled brief", product=data.get("product") or "",
                       goal="awareness", platforms=["instagram"], deliverable_type="reel", deliverables_per_creator=1,
                       required_elements={}, dos=[], donts=[], pay_model="hybrid", cpm_paise=0, flat_paise=0,
                       cap_paise=0, min_tier="bronze", niches=[], cities=[], max_creators=5,
                       usage_rights="organic", tracking_days=30, status="draft", policy_flags=[])
    for k in BRIEF_FIELDS:
        if k in data and data[k] is not None:
            setattr(b, k, data[k])
    b.required_elements = {"mention": f"@{org.instagram_handle}" if org.instagram_handle else None,
                           "hashtags": ["#ad"], "disclosure": True, "link_in_bio": False, "discount_code": None,
                           **(b.required_elements or {})}
    if "angles" in data and data["angles"] is not None:
        b.angles = [BriefAngle(position=i, title=a.get("title", ""), hook=a.get("hook", ""),
                               angle_text=a.get("angle_text") or a.get("why_now") or "", format=a.get("format"),
                               length_s=a.get("length_s"), why_now=a.get("why_now"), trend_ref=a.get("trend_ref"),
                               source=a.get("source", "brand")) for i, a in enumerate(data["angles"][:8])]
    if data.get("ai_draft_id"):
        b.ai_draft_id = data["ai_draft_id"]
    validate(b)
    if not brief:
        db.add(b)
    db.flush()
    audit(db, actor, "brief.saved", "brief", b.id, None, {"status": b.status})
    return b


def publish(db: Session, brief: Brief, org: Org, actor: str) -> Brief:
    from .ai import policy_check
    if brief.status not in ("draft", "paused"):
        raise conflict("not_publishable", f"brief is {brief.status}")
    validate(brief)
    pol = policy_check(db, brief, actor)
    brief.policy_flags = pol["issues"]
    if pol["blocked"]:
        open_item(db, "policy_block", "asci_precheck", "brief", brief.id, f"Brief “{brief.title}” blocked by policy pre-check",
                  {"issues": pol["issues"]})
        db.commit()
        raise ApiError(422, "policy_blocked", "This brief asks for something ASCI guidelines don't allow.",
                       {"issues": pol["issues"]})
    active = db.query(Hire).filter(Hire.brief_id == brief.id, Hire.status == "active").count()
    need = (brief.max_creators - active) * money.reserve_for(brief, org)
    avail = money.available(db, org.id)
    if avail < need:
        raise conflict("wallet_insufficient", "top up your wallet to cover every creator's maximum payout first",
                       needed_paise=need, available_paise=avail)
    brief.status, brief.published_at = "live", brief.published_at or now()
    audit(db, actor, "brief.published", "brief", brief.id, {"status": "draft"}, {"status": "live"})
    n = 0
    for cp in db.query(CreatorProfile).filter_by(eligible=True).all():
        ok, _ = matching.eligibility(db, cp, brief)
        if ok and n < 200:
            notify(db, cp.user_id, "brief_match", f"{org.name}: {brief.title}", f"/creator/briefs/{brief.id}")
            n += 1
    db.commit()
    return brief


def set_status(db: Session, brief: Brief, status: str, actor: str):
    allowed = {"live": ["paused", "closed"], "paused": ["live", "closed"], "draft": ["closed"]}
    if status not in allowed.get(brief.status, []):
        raise conflict("invalid_transition", f"cannot move a {brief.status} brief to {status}")
    before = brief.status
    brief.status = status
    audit(db, actor, "brief.status", "brief", brief.id, {"status": before}, {"status": status})
    db.commit()


# ------------------------------------------------------------------ applications
def apply(db: Session, cp: CreatorProfile, brief: Brief, pitch: str, sample_url: str | None) -> Application:
    ok, reasons = matching.eligibility(db, cp, brief)
    if not ok:
        raise ApiError(403, "not_eligible", "You don't qualify for this brief yet.", {"reasons": reasons})
    if db.query(Application).filter_by(brief_id=brief.id, creator_id=cp.user_id).first():
        raise conflict("already_applied", "you already applied to this brief")
    open_n = db.query(Application).filter(Application.creator_id == cp.user_id,
                                          Application.status.in_(["applied", "shortlisted"])).count()
    if open_n >= MAX_OPEN_APPLICATIONS:
        raise conflict("too_many_open_applications", f"you can have at most {MAX_OPEN_APPLICATIONS} open applications")
    if not pitch or len(pitch.strip()) < 5:
        raise bad("pitch_required", "add a one-line pitch")
    app = Application(brief_id=brief.id, creator_id=cp.user_id, pitch=pitch.strip()[:280], sample_url=sample_url,
                      invited=db.query(Invite).filter_by(brief_id=brief.id, creator_id=cp.user_id).first() is not None)
    db.add(app)
    db.flush()
    app.rank_score, app.rank_breakdown = matching.rank(db, app)
    for uid in org_members(db, brief.org_id):
        notify(db, uid, "application_received", f"{cp.display_name} applied to “{brief.title}”", f"/brand/briefs/{brief.id}")
    db.commit()
    return app


def withdraw(db: Session, app: Application):
    if app.status not in ("applied", "shortlisted"):
        raise conflict("not_withdrawable", "only open applications can be withdrawn")
    app.status, app.decided_at = "withdrawn", now()
    db.commit()


def contract_terms(db: Session, brief: Brief, org: Org, cp: CreatorProfile, reserve: int) -> dict:
    return {
        "parties": {"brand": org.name, "brand_gstin": org.gstin, "creator": cp.display_name,
                    "intermediary": "Flu (e-commerce operator; not a party to the content)"},
        "deliverables": f"{brief.deliverables_per_creator} × {brief.deliverable_type.title()} on "
                        + " / ".join(p.title() for p in brief.platforms) + ", posted from the creator's own account",
        "required_elements": brief.required_elements, "dos": brief.dos, "donts": brief.donts,
        "pay": {"model": brief.pay_model, "cpm_paise": brief.cpm_paise, "flat_paise": brief.flat_paise,
                "cap_paise_per_deliverable": money.per_deliverable_cap(brief),
                "verified_views": "Platform-reported views after Flu's anomaly filter",
                "tracking_days": brief.tracking_days},
        "escrow": {"reserved_paise": reserve, "provider": "Razorpay Route (funds on hold until approval)"},
        "approval": f"Brand approves or disputes within {APPROVAL_WINDOW_H} h of submission; auto-approved after that.",
        "usage_rights": USAGE.get(brief.usage_rights, brief.usage_rights),
        "disclosure": "Every post carries #ad / #collab / the paid-partnership label (ASCI).",
        "fee": f"Flu's platform fee of {round(money.take_rate(org) * 100)}% is deducted from each release.",
        "tax": "TDS under Section 194-O is withheld by Flu on each release; GST on Flu's fee is invoiced to the brand.",
        "disputes": f"Creator responds within {DISPUTE_RESPONSE_H} h; Flu ops decides within 48 h.",
        "deadline": brief.deadline.isoformat() if brief.deadline else None,
        "governing_law": "India",
    }


def accept(db: Session, app: Application, org: Org, actor: str) -> Hire:
    brief = db.get(Brief, app.brief_id)
    if brief.org_id != org.id:
        raise not_found("application")
    if app.status == "accepted":
        return db.query(Hire).filter_by(application_id=app.id).first()
    if app.status not in ("applied", "shortlisted"):
        raise conflict("not_acceptable", f"application is {app.status}")
    if brief.status != "live":
        raise conflict("brief_not_live", "publish the brief first")
    hired = db.query(Hire).filter(Hire.brief_id == brief.id, Hire.status != "cancelled").count()
    if hired >= brief.max_creators:
        raise conflict("brief_full", "all creator slots are filled")
    org_live = (db.query(Hire).join(Brief, Brief.id == Hire.brief_id)
                .filter(Brief.org_id == org.id, Hire.status == "active").count())
    if org_live >= PLAN_LIVE_CREATORS.get(org.plan, 5):
        raise conflict("plan_limit", f"your {org.plan.title()} plan allows {PLAN_LIVE_CREATORS[org.plan]} live creators")
    cp = db.get(CreatorProfile, app.creator_id)
    reserve = money.reserve_for(brief, org)
    hire = Hire(brief_id=brief.id, creator_id=cp.user_id, application_id=app.id, reserved_paise=reserve)
    db.add(hire)
    db.flush()
    money.reserve_hire(db, hire, org, actor)
    db.add(Contract(hire_id=hire.id, version=1, terms=contract_terms(db, brief, org, cp, reserve),
                    usage_rights=brief.usage_rights, brand_accepted_at=now()))
    app.status, app.decided_at = "accepted", now()
    audit(db, actor, "application.accepted", "application", app.id, {"status": "applied"}, {"hire_id": hire.id})
    notify(db, cp.user_id, "application_accepted", f"{org.name} hired you for “{brief.title}”.", "/creator/work")
    db.commit()
    return hire


def reject(db: Session, app: Application, actor: str):
    if app.status not in ("applied", "shortlisted"):
        raise conflict("not_rejectable", f"application is {app.status}")
    app.status, app.decided_at = "rejected", now()
    brief = db.get(Brief, app.brief_id)
    notify(db, app.creator_id, "application_rejected", f"“{brief.title}” went with other creators this time.",
           "/creator/briefs")
    db.commit()


def invite(db: Session, brief: Brief, org: Org, creator_ids: list[str]) -> int:
    limit = {"starter": 20, "growth": 100, "scale": 1000}.get(org.plan, 20)
    have = db.query(Invite).filter_by(brief_id=brief.id).count()
    n = 0
    for cid in creator_ids:
        if have + n >= limit:
            break
        if not db.get(CreatorProfile, cid) or db.query(Invite).filter_by(brief_id=brief.id, creator_id=cid).first():
            continue
        db.add(Invite(brief_id=brief.id, creator_id=cid))
        notify(db, cid, "invited", f"{org.name} invited you to “{brief.title}”", f"/creator/briefs/{brief.id}")
        n += 1
    db.commit()
    return n


# ------------------------------------------------------------------ contracts + deliverables
def accept_contract(db: Session, hire: Hire, creator_id: str) -> Contract:
    if hire.creator_id != creator_id:
        raise not_found("hire")
    c = db.query(Contract).filter_by(hire_id=hire.id).order_by(Contract.version.desc()).first()
    if not c.creator_accepted_at:
        c.creator_accepted_at = now()
        audit(db, creator_id, "contract.accepted", "contract", c.id)
        db.commit()
    return c


def check_required(brief: Brief, caption: str, paid_partnership: bool) -> dict:
    cap = (caption or "").lower()
    req = brief.required_elements or {}
    out = {}
    if req.get("mention"):
        out["mention"] = {"required": req["mention"], "ok": req["mention"].lower() in cap}
    for h in req.get("hashtags") or []:
        out[f"hashtag {h}"] = {"required": h, "ok": h.lower() in cap}
    out["disclosure"] = {"required": "#ad / #collab / #sponsored or paid-partnership label",
                         "ok": paid_partnership or any(t in cap for t in DISCLOSURE_TAGS)}
    if req.get("discount_code"):
        out["discount_code"] = {"required": req["discount_code"], "ok": req["discount_code"].lower() in cap}
    if req.get("link_in_bio"):
        out["link_in_bio"] = {"required": "link in bio", "ok": None, "note": "not readable via API; brand checks"}
    return out


def submit(db: Session, hire: Hire, creator_id: str, post_url: str, hook_id: str | None = None) -> Deliverable:
    if hire.creator_id != creator_id:
        raise not_found("hire")
    if hire.status != "active":
        raise conflict("hire_inactive", f"this hire is {hire.status}")
    brief = db.get(Brief, hire.brief_id)
    c = db.query(Contract).filter_by(hire_id=hire.id).order_by(Contract.version.desc()).first()
    if not c.creator_accepted_at:
        raise conflict("contract_pending", "accept the contract before posting")
    if db.query(Deliverable).filter_by(hire_id=hire.id).count() >= brief.deliverables_per_creator:
        raise conflict("all_submitted", "you've already submitted every deliverable for this hire")
    url = (post_url or "").strip()
    platform = "instagram" if "instagram.com" in url else "youtube" if ("youtube.com" in url or "youtu.be" in url) else None
    if not platform or platform not in brief.platforms:
        raise bad("wrong_platform", "paste an Instagram Reel or YouTube Short link for a platform this brief uses")
    acc = db.query(PlatformAccount).filter_by(creator_id=creator_id, platform=platform, status="active").first()
    if not acc:
        raise bad("not_connected", f"connect your {platform.title()} account first")
    from .connections import access_token
    prov = providers.social(platform, db)
    m = prov.find_media_by_permalink(access_token(db, acc), url)
    if not m:
        raise ApiError(422, "ownership_failed", f"We couldn't find this post on @{acc.handle}. Post from your connected account.")
    media = db.query(MediaItem).filter_by(platform_account_id=acc.id, external_media_id=m.id).first()
    if not media:
        media = MediaItem(platform_account_id=acc.id, external_media_id=m.id, media_type=m.media_type,
                          media_product_type=m.media_product_type, permalink=m.permalink, caption=m.caption,
                          posted_at=m.timestamp, duration_s=m.duration_s)
        db.add(media)
        db.flush()
    if db.query(Deliverable).filter_by(media_item_id=media.id).first():
        raise conflict("post_already_used", "this post was already submitted as a deliverable")
    paid = False
    if hasattr(prov, "db"):
        from ..models import FakeMedia
        fm = db.get(FakeMedia, m.id)
        paid = bool(fm and fm.paid_partnership)
    checks = check_required(brief, m.caption, paid)
    missing = [k for k, v in checks.items() if v["ok"] is False]
    if missing:
        raise ApiError(422, "required_elements_missing", "Your post is missing required elements: " + ", ".join(missing),
                       {"checks": checks})
    t = now()
    d = Deliverable(hire_id=hire.id, media_item_id=media.id, post_url=m.permalink, submitted_at=t,
                    verified_ownership=True, required_elements_ok=checks, status="submitted",
                    approval_deadline_at=t + timedelta(hours=APPROVAL_WINDOW_H),
                    tracking_ends_at=t + timedelta(days=brief.tracking_days))
    if hook_id:
        h = db.get(HookIssued, hook_id)
        if h and h.creator_id == creator_id:
            d.hook_id, h.used_media_id = h.id, media.id
    db.add(d)
    db.flush()
    tracking.start(db, d)
    audit(db, creator_id, "deliverable.submitted", "deliverable", d.id, None, {"url": d.post_url})
    for uid in org_members(db, brief.org_id):
        notify(db, uid, "deliverable_submitted", f"New post on “{brief.title}”: approve within 72 h.",
               f"/brand/briefs/{brief.id}?d={d.id}")
    db.commit()
    return d


def _deliverable_for_org(db: Session, d_id: str, org_id: str) -> tuple[Deliverable, Hire, Brief]:
    d = db.get(Deliverable, d_id)
    if not d:
        raise not_found("deliverable")
    hire = db.get(Hire, d.hire_id)
    brief = db.get(Brief, hire.brief_id)
    if brief.org_id != org_id:
        raise not_found("deliverable")
    return d, hire, brief


def approve(db: Session, d_id: str, org_id: str, actor: str, rating: dict | None = None) -> Deliverable:
    d, hire, brief = _deliverable_for_org(db, d_id, org_id)
    if d.status in ("approved", "auto_approved"):
        return d
    if d.status != "submitted":
        raise conflict("not_approvable", f"deliverable is {d.status}")
    d.status, d.approved_at = "approved", now()
    if rating:
        d.brand_rating = rating
    audit(db, actor, "deliverable.approved", "deliverable", d.id, {"status": "submitted"}, {"status": "approved"})
    money.release(db, d, actor)
    money.close_hire_if_done(db, hire, actor)
    notify(db, hire.creator_id, "deliverable_approved", f"“{brief.title}” approved. Earnings are being released.",
           "/creator/earnings")
    jobs.enqueue(db, "scoring.run", {"creator_id": hire.creator_id, "trigger": "deliverable"})
    db.commit()
    return d


def dispute(db: Session, d_id: str, org_id: str, actor: str, reason: str, evidence: list[str]) -> Dispute:
    d, hire, brief = _deliverable_for_org(db, d_id, org_id)
    if d.status != "submitted":
        raise conflict("not_disputable", f"deliverable is {d.status}")
    if now() > d.approval_deadline_at:
        raise conflict("window_closed", "the 72-hour approval window has closed")
    if not reason or len(reason.strip()) < 10:
        raise bad("reason_required", "explain what is wrong with the post (at least 10 characters)")
    d.status = "disputed"
    disp = Dispute(deliverable_id=d.id, raised_by=actor, reason=reason.strip(), evidence=evidence or [])
    db.add(disp)
    db.flush()
    open_item(db, "dispute", "brand_dispute", "dispute", disp.id, f"{brief.title}: {reason.strip()[:120]}",
              {"deliverable_id": d.id})
    audit(db, actor, "deliverable.disputed", "deliverable", d.id, {"status": "submitted"}, {"status": "disputed"})
    notify(db, hire.creator_id, "dispute_opened", f"Reason: {reason.strip()[:140]}", "/creator/work")
    db.commit()
    return disp


def respond_dispute(db: Session, disp: Dispute, creator_id: str, response: str):
    d = db.get(Deliverable, disp.deliverable_id)
    if db.get(Hire, d.hire_id).creator_id != creator_id:
        raise not_found("dispute")
    if disp.ops_decision:
        raise conflict("dispute_closed", "this dispute has been decided")
    if now() > disp.created_at + timedelta(hours=DISPUTE_RESPONSE_H):
        raise conflict("response_window_closed", "the 48-hour response window has closed")
    disp.creator_response, disp.creator_responded_at = response.strip()[:2000], now()
    db.commit()


def decide_dispute(db: Session, disp: Dispute, decision: str, actor: str, note: str | None):
    if decision not in ("approved", "rejected"):
        raise bad("invalid_decision", "decision must be approved or rejected")
    d = db.get(Deliverable, disp.deliverable_id)
    hire = db.get(Hire, d.hire_id)
    disp.ops_decision, disp.decided_by, disp.decided_at = decision, actor, now()
    disp.evidence = [*disp.evidence, {"ops_note": note}] if note else disp.evidence
    if decision == "approved":
        d.status, d.approved_at = "approved", now()
        money.release(db, d, actor)
    else:
        d.status, d.tracking_status = "rejected", "ended"
    money.close_hire_if_done(db, hire, actor)
    audit(db, actor, "dispute.decided", "dispute", disp.id, None, {"decision": decision})
    notify(db, hire.creator_id, "dispute_decided", f"Decision: {decision}.", "/creator/work")
    brief = db.get(Brief, hire.brief_id)
    for uid in org_members(db, brief.org_id):
        notify(db, uid, "dispute_decided", f"“{brief.title}”: {decision}.", f"/brand/briefs/{brief.id}")


def cancel_hire(db: Session, hire: Hire, actor: str):
    if db.query(Deliverable).filter_by(hire_id=hire.id).count():
        raise conflict("has_deliverables", "a hire with submitted posts can't be cancelled")
    money.close_hire_if_done(db, hire, actor, force=True)
    hire.status = "cancelled"
    db.commit()
