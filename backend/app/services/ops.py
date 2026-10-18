"""Audit log, ops queue and notifications (TS-1, TS-5, notify package)."""
from sqlalchemy.orm import Session

from ..clock import now
from ..models import AuditLog, Notification, OpsItem

TEMPLATES = {
    "audit_passed": ("Your account passed the audit", "Your Creator Score is ready."),
    "audit_flagged": ("We're reviewing your account", "Our team will review your account within 48 hours."),
    "brief_match": ("New brief you qualify for", ""),
    "invited": ("A brand invited you to a brief", ""),
    "application_received": ("New application", ""),
    "application_accepted": ("You're hired!", "Accept the contract to start."),
    "application_rejected": ("Application not selected", ""),
    "deliverable_submitted": ("Post submitted for approval", "You have 72 hours to approve or dispute."),
    "approval_reminder": ("Approval window closing", ""),
    "deliverable_approved": ("Post approved", "Earnings are being released."),
    "dispute_opened": ("A brand disputed your post", "Respond within 48 hours."),
    "dispute_decided": ("Dispute decided", ""),
    "payout_sent": ("Payout sent", ""),
    "payout_held_kyc": ("Complete KYC to get paid", "Add your PAN and bank or UPI to release your earnings."),
    "needs_reauth": ("Reconnect your account", "Tracking stops until you reconnect."),
    "post_deleted": ("A tracked post was deleted", "Accrual is frozen for this deliverable."),
    "wallet_credited": ("Wallet topped up", ""),
}


def audit(db: Session, actor_id: str | None, action: str, entity_type: str, entity_id: str,
          before: dict | None = None, after: dict | None = None, ip: str | None = None):
    db.add(AuditLog(actor_id=actor_id, action=action, entity_type=entity_type, entity_id=entity_id,
                    before=before, after=after, ip=ip))


def open_item(db: Session, type: str, reason_code: str, entity_type: str, entity_id: str,
              summary: str, details: dict | None = None) -> OpsItem:
    existing = db.query(OpsItem).filter_by(type=type, entity_type=entity_type, entity_id=entity_id,
                                           status="open").first()
    if existing:
        existing.details = {**(existing.details or {}), **(details or {})}
        return existing
    item = OpsItem(type=type, reason_code=reason_code, entity_type=entity_type, entity_id=entity_id,
                   summary=summary, details=details or {})
    db.add(item)
    db.flush()
    return item


def notify(db: Session, user_id: str, template: str, body: str | None = None, link: str | None = None,
           title: str | None = None):
    t, b = TEMPLATES.get(template, (template, ""))
    db.add(Notification(user_id=user_id, template=template, title=title or t, body=body or b, link=link,
                        channels=["in_app", "push", "whatsapp"]))


def resolve(db: Session, item: OpsItem, decision: str, note: str | None, actor_id: str):
    item.status, item.decision, item.note = "resolved", decision, note
    item.resolved_at, item.resolved_by = now(), actor_id
    audit(db, actor_id, "ops.resolve", "ops_item", item.id, None, {"decision": decision, "note": note})
