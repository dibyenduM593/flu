"use client";

import { useState } from "react";
import { Check, X } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { datetime, num, rel, title } from "@/lib/format";
import { useSession } from "@/lib/session";
import { Chips, Empty, ErrorNote, Loading, S, Status } from "@/components/ui";

const TYPES = [
  { id: "", label: "All open" }, { id: "dispute", label: "Disputes" }, { id: "view_anomaly", label: "Held views" },
  { id: "fraud_flag", label: "Fraud flags" }, { id: "kyc_fail", label: "KYC" }, { id: "policy_block", label: "Policy" },
  { id: "reconcile", label: "Reconciliation" },
];

const ACTIONS: Record<string, [string, string, string][]> = {
  dispute: [["approved", "Pay the creator", "primary"], ["rejected", "Reject the post", "danger"]],
  view_anomaly: [["cleared", "Clear: count the views", "primary"], ["rejected", "Reject the views", "danger"]],
  fraud_flag: [["cleared", "Clear the account", "primary"], ["rejected", "Block the account", "danger"]],
};

function Item({ i, onDone }: { i: any; onDone: () => void }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const { toast } = useSession();
  const decide = async (decision: string) => {
    setBusy(true);
    try {
      await api(`/v1/ops/queue/${i.id}/resolve`, { body: { decision, note: note || null } });
      toast("Resolved and logged");
      onDone();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };
  const acts = ACTIONS[i.type] || [["resolved", "Mark resolved", "primary"]];
  const det = i.details || {};
  return (
    <section className="card stack fade-in">
      <div className="row between wrap-row">
        <div className="row" style={{ gap: 8 }}><span className="tag warn">{title(i.type)}</span><span className="muted small">{title(i.reason_code)}</span></div>
        <span className="muted small">{rel(i.created_at)}</span>
      </div>
      <strong style={{ fontSize: 16 }}>{i.summary}</strong>
      {i.dispute && (
        <div className="grid cols-2" style={{ gap: 10 }}>
          <div className="card soft tight"><div className="muted small">Brand says</div><p>{i.dispute.reason}</p></div>
          <div className="card soft tight"><div className="muted small">Creator says</div><p>{i.dispute.creator_response || <span className="faint">No response yet (48 h window)</span>}</p></div>
        </div>
      )}
      {i.snapshot && (
        <div className="kv small">
          <div><span className="k">Views at poll</span><span className="num">{num(i.snapshot.views)}</span></div>
          <div><span className="k">Held delta</span><span className="num">{num(det.delta_views)}</span></div>
          <div><span className="k">Rule</span><span>{det.reason}</span></div>
          <div><span className="k">Polled</span><span>{datetime(i.snapshot.polled_at)}</span></div>
        </div>
      )}
      {i.type === "fraud_flag" && det.metrics && (
        <div className="kv small">
          {(["followers", "median_views", "engagement_rate", "view_follower_ratio", "follower_growth_30d"] as const).map((k) => (
            <div key={k}><span className="k">{title(k)}</span><span className="num">{det.metrics[k] ?? "—"}</span></div>
          ))}
        </div>
      )}
      {(i.type === "policy_block" || i.type === "reconcile" || i.type === "kyc_fail") && <pre className="small muted" style={{ whiteSpace: "pre-wrap", margin: 0, fontFamily: "inherit" }}>{JSON.stringify(det, null, 2)}</pre>}
      {i.status === "open" ? (
        <div className="row wrap-row">
          <input className="input" style={{ flex: 1, minWidth: 200 }} placeholder="Note for the audit log" value={note} onChange={(e) => setNote(e.target.value)} />
          {acts.map(([d, l, c]) => (
            <button key={d} className={`btn ${c}`} disabled={busy} onClick={() => decide(d)}>{c === "danger" ? <X size={15} /> : <Check size={15} strokeWidth={2} />} {l}</button>
          ))}
        </div>
      ) : <div className="row"><Status s="resolved" /><span className="muted small">{i.decision}{i.note ? ` · ${i.note}` : ""}</span></div>}
    </section>
  );
}

export default function Queue() {
  const [type, setType] = useState("");
  const [status, setStatus] = useState("open");
  const { data, error, loading, reload } = useApi<any>(`/v1/ops/queue?status=${status}${type ? `&type=${type}` : ""}`);
  const counts = data?.open_counts || {};
  return (
    <>
      <div className="page-title">
        <div><h1>Trust queue</h1><p>Flagged accounts, held views, KYC failures and disputes. Target: every dispute decided within 48 hours.</p></div>
        <Chips value={status} onChange={setStatus} items={[{ id: "open", label: "Open" }, { id: "all", label: "All" }]} />
      </div>
      <Chips value={type} onChange={setType} items={TYPES.map((t) => ({ id: t.id, label: t.id && counts[t.id] ? `${t.label} ${counts[t.id]}` : t.label }))} />
      <ErrorNote error={error} />
      {loading && !data ? <Loading /> : data?.data.length ? data.data.map((i: any) => <Item key={i.id} i={i} onDone={reload} />)
        : <div className="card"><Empty title="Queue is clear" icon={<Check size={28} strokeWidth={S} />} /></div>}
    </>
  );
}
