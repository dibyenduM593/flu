"""Data model (PRD § Data model). Money is integer paise; timestamps are UTC; ids are UUIDv7.

Append-only tables: ledger_entries, view_snapshots, view_ledger, audit_log, score_runs.
Balances are always derived from ledger_entries, never stored.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    JSON, BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, Numeric, String, Text,
    TypeDecorator, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, uuid7


class UTCDateTime(TypeDecorator):
    """Stores naive UTC, always returns tz-aware UTC (SQLite drops tzinfo)."""
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)


def _id():
    return mapped_column(String(36), primary_key=True, default=uuid7)


def _now():
    from .clock import now
    return now()


TS = UTCDateTime


# ---------------------------------------------------------------- identity
class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = _id()
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20))  # creator | brand_member | ops
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(TS, default=_now)
    updated_at: Mapped[datetime] = mapped_column(TS, default=_now, onupdate=_now)


class OtpCode(Base):
    __tablename__ = "otp_codes"
    id: Mapped[str] = _id()
    phone: Mapped[str] = mapped_column(String(20), index=True)
    code_hash: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(TS)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TS, default=_now)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id: Mapped[str] = _id()  # jti
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(TS)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TS, default=_now)


class Org(Base):
    __tablename__ = "orgs"
    id: Mapped[str] = _id()
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(20), default="brand")  # brand | agency
    plan: Mapped[str] = mapped_column(String(20), default="starter")  # starter | growth | scale
    gstin: Mapped[str | None] = mapped_column(String(20))
    gst_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    pan: Mapped[str | None] = mapped_column(String(12))
    category: Mapped[str | None] = mapped_column(String(60))
    city: Mapped[str | None] = mapped_column(String(80))
    website: Mapped[str | None] = mapped_column(String(200))
    instagram_handle: Mapped[str | None] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(TS, default=_now)


class OrgMember(Base):
    __tablename__ = "org_members"
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(20), default="owner")


class CreatorProfile(Base):
    __tablename__ = "creator_profiles"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120))
    city: Mapped[str | None] = mapped_column(String(80))
    state: Mapped[str | None] = mapped_column(String(80))
    bio: Mapped[str | None] = mapped_column(Text)
    niches: Mapped[list] = mapped_column(JSON, default=list)
    niche_confidence: Mapped[dict] = mapped_column(JSON, default=dict)
    niches_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    tier: Mapped[str] = mapped_column(String(12), default="bronze")
    score: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    streak_weeks: Mapped[int] = mapped_column(Integer, default=0)
    points: Mapped[int] = mapped_column(Integer, default=0)
    kyc_status: Mapped[str] = mapped_column(String(20), default="none")  # none | pending | verified | failed
    eligible: Mapped[bool] = mapped_column(Boolean, default=False)  # passes fraud screen
    created_at: Mapped[datetime] = mapped_column(TS, default=_now)
    updated_at: Mapped[datetime] = mapped_column(TS, default=_now, onupdate=_now)


# ---------------------------------------------------------------- connections + audit
class PlatformAccount(Base):
    __tablename__ = "platform_accounts"
    id: Mapped[str] = _id()
    creator_id: Mapped[str] = mapped_column(ForeignKey("creator_profiles.user_id"), index=True)
    platform: Mapped[str] = mapped_column(String(12))  # instagram | youtube
    external_id: Mapped[str] = mapped_column(String(80))
    handle: Mapped[str] = mapped_column(String(120))
    account_type: Mapped[str | None] = mapped_column(String(20))
    follower_count: Mapped[int] = mapped_column(Integer, default=0)
    access_token_enc: Mapped[str | None] = mapped_column(Text)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(TS)
    token_issued_at: Mapped[datetime | None] = mapped_column(TS)
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | revoked | needs_reauth
    connected_at: Mapped[datetime] = mapped_column(TS, default=_now)
    last_synced_at: Mapped[datetime | None] = mapped_column(TS)
    __table_args__ = (UniqueConstraint("platform", "external_id"),)


class AccountAudit(Base):
    __tablename__ = "account_audits"
    id: Mapped[str] = _id()
    platform_account_id: Mapped[str] = mapped_column(ForeignKey("platform_accounts.id"), index=True)
    run_at: Mapped[datetime] = mapped_column(TS, default=_now)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    fraud_flags: Mapped[list] = mapped_column(JSON, default=list)
    result: Mapped[str] = mapped_column(String(10))  # pass | flag | fail


class MediaItem(Base):
    __tablename__ = "media_items"
    id: Mapped[str] = _id()
    platform_account_id: Mapped[str] = mapped_column(ForeignKey("platform_accounts.id"))
    external_media_id: Mapped[str] = mapped_column(String(80))
    media_type: Mapped[str] = mapped_column(String(20))
    media_product_type: Mapped[str | None] = mapped_column(String(20))
    permalink: Mapped[str] = mapped_column(String(300))
    caption: Mapped[str | None] = mapped_column(Text)
    posted_at: Mapped[datetime] = mapped_column(TS)
    thumbnail_url: Mapped[str | None] = mapped_column(String(300))
    duration_s: Mapped[int | None] = mapped_column(Integer)
    last_metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    metrics_fetched_at: Mapped[datetime | None] = mapped_column(TS)
    __table_args__ = (
        UniqueConstraint("platform_account_id", "external_media_id"),
        Index("ix_media_account_posted", "platform_account_id", "posted_at"),
    )


# ---------------------------------------------------------------- briefs
class Brief(Base):
    __tablename__ = "briefs"
    id: Mapped[str] = _id()
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    product: Mapped[str] = mapped_column(Text)
    goal: Mapped[str] = mapped_column(String(20), default="awareness")  # awareness | installs | orders
    platforms: Mapped[list] = mapped_column(JSON, default=lambda: ["instagram"])
    deliverable_type: Mapped[str] = mapped_column(String(20), default="reel")  # reel | short
    deliverables_per_creator: Mapped[int] = mapped_column(Integer, default=1)
    required_elements: Mapped[dict] = mapped_column(JSON, default=dict)
    dos: Mapped[list] = mapped_column(JSON, default=list)
    donts: Mapped[list] = mapped_column(JSON, default=list)
    pay_model: Mapped[str] = mapped_column(String(10), default="hybrid")  # cpm | flat | hybrid
    cpm_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    flat_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    cap_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    min_tier: Mapped[str] = mapped_column(String(12), default="bronze")
    niches: Mapped[list] = mapped_column(JSON, default=list)
    cities: Mapped[list] = mapped_column(JSON, default=list)
    max_creators: Mapped[int] = mapped_column(Integer, default=5)
    deadline: Mapped[datetime | None] = mapped_column(TS)
    usage_rights: Mapped[str] = mapped_column(String(20), default="organic")  # organic | organic_paid_90d | paid_perpetual
    tracking_days: Mapped[int] = mapped_column(Integer, default=30)
    status: Mapped[str] = mapped_column(String(10), default="draft")  # draft | live | paused | closed
    ai_draft_id: Mapped[str | None] = mapped_column(ForeignKey("ai_jobs.id"))
    policy_flags: Mapped[list] = mapped_column(JSON, default=list)
    published_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = mapped_column(TS, default=_now)
    updated_at: Mapped[datetime] = mapped_column(TS, default=_now, onupdate=_now)
    angles = relationship("BriefAngle", cascade="all, delete-orphan", order_by="BriefAngle.position")


class BriefAngle(Base):
    __tablename__ = "brief_angles"
    id: Mapped[str] = _id()
    brief_id: Mapped[str] = mapped_column(ForeignKey("briefs.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(200))
    hook: Mapped[str] = mapped_column(Text)
    angle_text: Mapped[str] = mapped_column(Text, default="")
    format: Mapped[str | None] = mapped_column(String(60))
    length_s: Mapped[int | None] = mapped_column(Integer)
    why_now: Mapped[str | None] = mapped_column(Text)
    trend_ref: Mapped[str | None] = mapped_column(String(300))
    source: Mapped[str] = mapped_column(String(10), default="ai")  # ai | brand


class Application(Base):
    __tablename__ = "applications"
    id: Mapped[str] = _id()
    brief_id: Mapped[str] = mapped_column(ForeignKey("briefs.id"))
    creator_id: Mapped[str] = mapped_column(ForeignKey("creator_profiles.user_id"), index=True)
    pitch: Mapped[str] = mapped_column(Text)
    sample_url: Mapped[str | None] = mapped_column(String(300))
    invited: Mapped[bool] = mapped_column(Boolean, default=False)
    rank_score: Mapped[float] = mapped_column(Float, default=0)
    rank_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(12), default="applied")  # applied | shortlisted | accepted | rejected | withdrawn
    created_at: Mapped[datetime] = mapped_column(TS, default=_now)
    decided_at: Mapped[datetime | None] = mapped_column(TS)
    __table_args__ = (
        UniqueConstraint("brief_id", "creator_id"),
        Index("ix_app_brief_rank", "brief_id", "rank_score"),
    )


class Invite(Base):
    __tablename__ = "invites"
    id: Mapped[str] = _id()
    brief_id: Mapped[str] = mapped_column(ForeignKey("briefs.id"))
    creator_id: Mapped[str] = mapped_column(ForeignKey("creator_profiles.user_id"))
    created_at: Mapped[datetime] = mapped_column(TS, default=_now)
    __table_args__ = (UniqueConstraint("brief_id", "creator_id"),)


class Hire(Base):
    __tablename__ = "hires"
    id: Mapped[str] = _id()
    brief_id: Mapped[str] = mapped_column(ForeignKey("briefs.id"), index=True)
    creator_id: Mapped[str] = mapped_column(ForeignKey("creator_profiles.user_id"), index=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"))
    reserved_paise: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(12), default="active")  # active | completed | cancelled
    created_at: Mapped[datetime] = mapped_column(TS, default=_now)
    closed_at: Mapped[datetime | None] = mapped_column(TS)


class Contract(Base):
    __tablename__ = "contracts"
    id: Mapped[str] = _id()
    hire_id: Mapped[str] = mapped_column(ForeignKey("hires.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    terms: Mapped[dict] = mapped_column(JSON)
    usage_rights: Mapped[str] = mapped_column(String(20))
    creator_accepted_at: Mapped[datetime | None] = mapped_column(TS)
    brand_accepted_at: Mapped[datetime | None] = mapped_column(TS)


class Deliverable(Base):
    __tablename__ = "deliverables"
    id: Mapped[str] = _id()
    hire_id: Mapped[str] = mapped_column(ForeignKey("hires.id"), index=True)
    media_item_id: Mapped[str] = mapped_column(ForeignKey("media_items.id"))
    post_url: Mapped[str] = mapped_column(String(300))
    submitted_at: Mapped[datetime] = mapped_column(TS, default=_now)
    verified_ownership: Mapped[bool] = mapped_column(Boolean, default=False)
    required_elements_ok: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(14), default="submitted")  # submitted | approved | disputed | auto_approved | rejected
    approved_at: Mapped[datetime | None] = mapped_column(TS)
    approval_deadline_at: Mapped[datetime] = mapped_column(TS)
    tracking_status: Mapped[str] = mapped_column(String(10), default="tracking")  # tracking | frozen | ended
    tracking_ends_at: Mapped[datetime] = mapped_column(TS)
    next_poll_at: Mapped[datetime | None] = mapped_column(TS)
    hook_id: Mapped[str | None] = mapped_column(ForeignKey("hooks_issued.id"))
    brand_rating: Mapped[dict | None] = mapped_column(JSON)


class ViewSnapshot(Base):
    __tablename__ = "view_snapshots"
    id: Mapped[str] = _id()
    deliverable_id: Mapped[str] = mapped_column(ForeignKey("deliverables.id"))
    polled_at: Mapped[datetime] = mapped_column(TS)
    views: Mapped[int] = mapped_column(BigInteger)
    reach: Mapped[int] = mapped_column(BigInteger, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    saves: Mapped[int] = mapped_column(Integer, default=0)
    shares: Mapped[int] = mapped_column(Integer, default=0)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    anomaly: Mapped[str] = mapped_column(String(10), default="none")  # none | held | cleared | rejected
    anomaly_reason: Mapped[str | None] = mapped_column(String(200))
    __table_args__ = (Index("ix_snap_deliv_polled", "deliverable_id", "polled_at"),)


class ViewLedger(Base):
    __tablename__ = "view_ledger"
    id: Mapped[str] = _id()
    deliverable_id: Mapped[str] = mapped_column(ForeignKey("deliverables.id"), index=True)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("view_snapshots.id"), unique=True)
    delta_views: Mapped[int] = mapped_column(BigInteger)
    verified: Mapped[bool] = mapped_column(Boolean, default=True)
    accrued_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(TS, default=_now)


# ---------------------------------------------------------------- money
class Wallet(Base):
    __tablename__ = "wallets"
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id"), primary_key=True)
    currency: Mapped[str] = mapped_column(String(3), default="INR")


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    id: Mapped[str] = _id()
    wallet_id: Mapped[str] = mapped_column(ForeignKey("wallets.org_id"))
    # topup | reserve | release_reserve | payout | fee | fee_gst | tds_withheld | refund | adjustment
    kind: Mapped[str] = mapped_column(String(20))
    amount_paise: Mapped[int] = mapped_column(BigInteger)  # signed
    ref_type: Mapped[str] = mapped_column(String(20))
    ref_id: Mapped[str] = mapped_column(String(36))
    memo: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(TS, default=_now)
    created_by: Mapped[str | None] = mapped_column(String(36))
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True)
    __table_args__ = (Index("ix_ledger_wallet_created", "wallet_id", "created_at"),)


class Payment(Base):
    """A captured brand top-up: the source payment that Route transfers are created against."""
    __tablename__ = "payments"
    id: Mapped[str] = _id()
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id"), index=True)
    rzp_order_id: Mapped[str] = mapped_column(String(60), unique=True)
    rzp_payment_id: Mapped[str | None] = mapped_column(String(60))
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(12), default="created")  # created | captured | failed | refunded
    created_at: Mapped[datetime] = mapped_column(TS, default=_now)
    captured_at: Mapped[datetime | None] = mapped_column(TS)


class Transfer(Base):
    """Razorpay Route transfer holding a hire's reserve (on_hold until approval)."""
    __tablename__ = "transfers"
    id: Mapped[str] = _id()
    hire_id: Mapped[str] = mapped_column(ForeignKey("hires.id"), index=True)
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id"))
    rzp_transfer_id: Mapped[str] = mapped_column(String(60))
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    reversed_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    on_hold: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=_now)


class Payout(Base):
    __tablename__ = "payouts"
    id: Mapped[str] = _id()
    creator_id: Mapped[str] = mapped_column(ForeignKey("creator_profiles.user_id"), index=True)
    deliverable_id: Mapped[str] = mapped_column(ForeignKey("deliverables.id"), index=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id"), index=True)
    amount_paise: Mapped[int] = mapped_column(BigInteger)  # gross earned by creator for this batch
    fee_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    gst_paise: Mapped[int] = mapped_column(BigInteger, default=0)  # GST on Flu's fee, billed to brand
    tds_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    net_paise: Mapped[int] = mapped_column(BigInteger)
    rzp_transfer_id: Mapped[str | None] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(12), default="queued")  # queued | processing | processed | reversed | failed
    hold_reason: Mapped[str | None] = mapped_column(String(60))
    utr: Mapped[str | None] = mapped_column(String(40))
    invoice_no: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(TS, default=_now)
    settle_after: Mapped[datetime | None] = mapped_column(TS)
    processed_at: Mapped[datetime | None] = mapped_column(TS)


class KycRecord(Base):
    __tablename__ = "kyc_records"
    creator_id: Mapped[str] = mapped_column(ForeignKey("creator_profiles.user_id"), primary_key=True)
    pan_hash: Mapped[str | None] = mapped_column(String(128))
    pan_salt: Mapped[str | None] = mapped_column(String(64))
    pan_last4: Mapped[str | None] = mapped_column(String(4))
    pan_name: Mapped[str | None] = mapped_column(String(120))
    name_match: Mapped[float | None] = mapped_column(Float)
    bank_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    account_tail: Mapped[str | None] = mapped_column(String(8))
    ifsc: Mapped[str | None] = mapped_column(String(11))
    vpa: Mapped[str | None] = mapped_column(String(80))
    fund_account_id: Mapped[str | None] = mapped_column(String(60))
    linked_account_id: Mapped[str | None] = mapped_column(String(60))
    gstin: Mapped[str | None] = mapped_column(String(20))
    aadhaar_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(12), default="pending")
    fail_reason: Mapped[str | None] = mapped_column(String(200))
    verified_at: Mapped[datetime | None] = mapped_column(TS)
    provider_ref: Mapped[str | None] = mapped_column(String(60))


# ---------------------------------------------------------------- scoring + ai
class ScoreRun(Base):
    __tablename__ = "score_runs"
    id: Mapped[str] = _id()
    creator_id: Mapped[str] = mapped_column(ForeignKey("creator_profiles.user_id"), index=True)
    run_at: Mapped[datetime] = mapped_column(TS, default=_now)
    features: Mapped[dict] = mapped_column(JSON)
    breakdown: Mapped[dict] = mapped_column(JSON)
    score: Mapped[float] = mapped_column(Numeric(5, 2))
    tier: Mapped[str] = mapped_column(String(12))
    model_version: Mapped[str] = mapped_column(String(40))
    trigger: Mapped[str] = mapped_column(String(30), default="audit")


class AiJob(Base):
    __tablename__ = "ai_jobs"
    id: Mapped[str] = _id()
    kind: Mapped[str] = mapped_column(String(20))  # trend_brief | hooks | diagnosis | niche_classify | policy_check
    status: Mapped[str] = mapped_column(String(10), default="queued")  # queued | running | done | failed
    input: Mapped[dict] = mapped_column(JSON)
    output: Mapped[dict | None] = mapped_column(JSON)
    model: Mapped[str | None] = mapped_column(String(60))
    prompt_version: Mapped[str | None] = mapped_column(String(40))
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_paise: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    feedback: Mapped[str | None] = mapped_column(String(10))  # up | down
    created_by: Mapped[str | None] = mapped_column(String(36), index=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=_now)


class HookIssued(Base):
    __tablename__ = "hooks_issued"
    id: Mapped[str] = _id()
    creator_id: Mapped[str] = mapped_column(ForeignKey("creator_profiles.user_id"), index=True)
    brief_id: Mapped[str | None] = mapped_column(ForeignKey("briefs.id"), index=True)
    ai_job_id: Mapped[str | None] = mapped_column(ForeignKey("ai_jobs.id"))
    pattern: Mapped[str] = mapped_column(String(20))
    first_line: Mapped[str] = mapped_column(Text)
    on_screen_text: Mapped[str] = mapped_column(Text)
    why_it_fits: Mapped[str] = mapped_column(Text)
    used_media_id: Mapped[str | None] = mapped_column(ForeignKey("media_items.id"))
    created_at: Mapped[datetime] = mapped_column(TS, default=_now)


# ---------------------------------------------------------------- trust + ops
class Dispute(Base):
    __tablename__ = "disputes"
    id: Mapped[str] = _id()
    deliverable_id: Mapped[str] = mapped_column(ForeignKey("deliverables.id"), index=True)
    raised_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    creator_response: Mapped[str | None] = mapped_column(Text)
    creator_responded_at: Mapped[datetime | None] = mapped_column(TS)
    ops_decision: Mapped[str | None] = mapped_column(String(12))  # approved | rejected
    decided_by: Mapped[str | None] = mapped_column(String(36))
    decided_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = mapped_column(TS, default=_now)


class OpsItem(Base):
    __tablename__ = "ops_items"
    id: Mapped[str] = _id()
    type: Mapped[str] = mapped_column(String(20))  # fraud_flag | view_anomaly | kyc_fail | dispute | policy_block | reconcile
    reason_code: Mapped[str] = mapped_column(String(40))
    entity_type: Mapped[str] = mapped_column(String(30))
    entity_id: Mapped[str] = mapped_column(String(36))
    summary: Mapped[str] = mapped_column(String(300))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(10), default="open")  # open | resolved
    decision: Mapped[str | None] = mapped_column(String(20))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, default=_now)
    resolved_at: Mapped[datetime | None] = mapped_column(TS)
    resolved_by: Mapped[str | None] = mapped_column(String(36))


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[str] = _id()
    actor_id: Mapped[str | None] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(60))
    entity_type: Mapped[str] = mapped_column(String(30))
    entity_id: Mapped[str] = mapped_column(String(36))
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
    ip: Mapped[str | None] = mapped_column(String(60))
    at: Mapped[datetime] = mapped_column(TS, default=_now)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[str] = _id()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    template: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str | None] = mapped_column(String(200))
    channels: Mapped[list] = mapped_column(JSON, default=list)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TS, default=_now)


# ---------------------------------------------------------------- infra
class Job(Base):
    """Postgres-backed queue in the PRD (Procrastinate); a table + in-process worker here."""
    __tablename__ = "jobs"
    id: Mapped[str] = _id()
    kind: Mapped[str] = mapped_column(String(40))
    args: Mapped[dict] = mapped_column(JSON, default=dict)
    run_at: Mapped[datetime] = mapped_column(TS, index=True)
    status: Mapped[str] = mapped_column(String(10), default="queued")  # queued | running | done | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    dedupe_key: Mapped[str | None] = mapped_column(String(160), unique=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(TS)


class SimState(Base):
    __tablename__ = "sim_state"
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)  # provider event id
    provider: Mapped[str] = mapped_column(String(20))
    event: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)
    verified: Mapped[bool] = mapped_column(Boolean)
    received_at: Mapped[datetime] = mapped_column(TS, default=_now)


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36))
    path: Mapped[str] = mapped_column(String(200))
    status_code: Mapped[int] = mapped_column(Integer)
    response: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(TS, default=_now)


# ---------------------------------------------------------------- fake providers' own world
class FakeAccount(Base):
    """An account inside the simulated Instagram / YouTube."""
    __tablename__ = "fake_accounts"
    external_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    platform: Mapped[str] = mapped_column(String(12))
    handle: Mapped[str] = mapped_column(String(120), index=True)
    account_type: Mapped[str] = mapped_column(String(20))  # MEDIA_CREATOR | BUSINESS | PERSONAL (IG); CHANNEL (YT)
    followers: Mapped[int] = mapped_column(Integer)
    persona: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(TS, default=_now)


class FakeMedia(Base):
    __tablename__ = "fake_media"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)  # external media id
    account_external_id: Mapped[str] = mapped_column(ForeignKey("fake_accounts.external_id"), index=True)
    shortcode: Mapped[str] = mapped_column(String(20), unique=True)
    permalink: Mapped[str] = mapped_column(String(300), index=True)
    caption: Mapped[str] = mapped_column(Text, default="")
    media_type: Mapped[str] = mapped_column(String(20), default="VIDEO")
    media_product_type: Mapped[str] = mapped_column(String(20), default="REELS")
    posted_at: Mapped[datetime] = mapped_column(TS)
    duration_s: Mapped[int] = mapped_column(Integer, default=30)
    final_views: Mapped[int] = mapped_column(BigInteger)
    tau_hours: Mapped[float] = mapped_column(Float, default=30)
    eng_rate: Mapped[float] = mapped_column(Float, default=0.05)
    reach_ratio: Mapped[float] = mapped_column(Float, default=0.8)
    bot_views: Mapped[int] = mapped_column(BigInteger, default=0)
    bot_at: Mapped[datetime | None] = mapped_column(TS)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    paid_partnership: Mapped[bool] = mapped_column(Boolean, default=False)


class FakeRzpObject(Base):
    __tablename__ = "fake_rzp_objects"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    data: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(TS, default=_now)
