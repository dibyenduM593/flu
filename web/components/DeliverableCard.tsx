"use client";

import { useEffect, useState } from "react";
import { Check, ExternalLink, ShieldAlert } from "lucide-react";
import { api } from "@/lib/api";
import { datetime, inr, num, rel, short } from "@/lib/format";
import { AreaChart } from "./charts";
import { Plat, S, Status } from "./ui";

/** Shared by creator and brand views: status, tracking, money, and the views curve. */
export function DeliverableCard({ d, actions, showChart = false }: { d: any; actions?: React.ReactNode; showChart?: boolean }) {
  const [snaps, setSnaps] = useState<any[] | null>(null);
  const [open, setOpen] = useState(showChart);
  const toggle = async () => {
    if (!snaps) {
      const full = await api(`/v1/deliverables/${d.id}`);
      setSnaps(full.snapshots);
    }
    setOpen(!open);
  };
  useEffect(() => {
    if (showChart) api(`/v1/deliverables/${d.id}`).then((f) => setSnaps(f.snapshots)).catch(() => {});
  }, [showChart, d.id]);
  const m = d.metrics || {};
  const steps = [
    { label: "Submitted", at: d.submitted_at, done: true },
    {
      label: d.status === "auto_approved" ? "Auto-approved" : d.status === "rejected" ? "Rejected" : d.status === "disputed" ? "Disputed, with Flu ops"
        : d.status === "submitted" ? "Brand review" : "Approved",
      at: d.approved_at || (d.status === "submitted" ? `Auto-approves ${rel(d.approval_deadline_at)}` : null),
      done: ["approved", "auto_approved"].includes(d.status), now: ["submitted", "disputed"].includes(d.status),
    },
    { label: d.tracking_status === "frozen" ? "Tracking frozen (post removed)" : d.tracking_status === "ended" ? "Tracking window closed" : "Counting verified views",
      at: d.tracking_status === "tracking" ? `Until ${datetime(d.tracking_ends_at)}` : null, done: d.tracking_status !== "tracking", now: d.tracking_status === "tracking" && d.status !== "submitted" },
  ];
  return (
    <div className="card soft stack">
      <div className="row between wrap-row">
        <div className="row"><Plat p={d.platform}>@{d.handle}</Plat><Status s={d.status} /></div>
        <a href={d.post_url} target="_blank" rel="noreferrer" className="link">Open post <ExternalLink size={13} /></a>
      </div>
      {d.caption && <p className="muted small" style={{ whiteSpace: "pre-wrap" }}>{d.caption}</p>}
      <div className="grid cols-4" style={{ gap: 8 }}>
        <div className="card tight"><div className="muted small">Verified views</div><div className="strong num" style={{ fontSize: 18 }}>{num(d.money.verified_views)}</div></div>
        <div className="card tight"><div className="muted small">Engagement</div><div className="strong num" style={{ fontSize: 18 }}>{short((m.likes || 0) + (m.comments || 0) + (m.saves || 0) + (m.shares || 0))}</div></div>
        <div className="card tight"><div className="muted small">Earned so far</div><div className="strong num" style={{ fontSize: 18 }}>{inr(d.money.accrued_paise)}</div></div>
        <div className="card tight"><div className="muted small">Released</div><div className="strong num" style={{ fontSize: 18 }}>{inr(d.money.released_paise)}</div></div>
      </div>
      {d.held_snapshots > 0 && (
        <div className="note warn"><ShieldAlert size={16} strokeWidth={S} />A jump in views with almost no engagement is held for review. It isn’t counted until our team clears it.</div>
      )}
      <div className="timeline">
        {steps.map((s) => (
          <div key={s.label} className={`t ${s.done ? "done" : s.now ? "now" : ""}`}>
            <span className="b">{s.done && <Check size={13} strokeWidth={2.5} />}</span>
            <div><div className="strong small">{s.label}</div>{s.at && <div className="muted small">{s.at.includes("T") ? datetime(s.at) : s.at}</div>}</div>
          </div>
        ))}
      </div>
      {d.dispute && (
        <div className="note bad" style={{ display: "grid" }}>
          <strong>Dispute: {d.dispute.reason}</strong>
          {d.dispute.creator_response && <span>Creator response: {d.dispute.creator_response}</span>}
          {d.dispute.ops_decision && <span>Decision: {d.dispute.ops_decision}</span>}
        </div>
      )}
      <div className="row between wrap-row">
        <button className="btn sm" style={{ background: "var(--surface)" }} onClick={toggle}>{open ? "Hide" : "Show"} views over time</button>
        {actions}
      </div>
      {open && snaps && (
        snaps.length > 1 ? (
          <AreaChart values={snaps.map((s) => s.views)} labels={snaps.map((s) => datetime(s.polled_at).split(",")[0])}
            label="Views at each poll" every={Math.ceil(snaps.length / 6)} />
        ) : <p className="muted small">First reads arrive at +1 h, +6 h and +24 h after you submit.</p>
      )}
    </div>
  );
}
