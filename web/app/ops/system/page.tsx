"use client";

import { useState } from "react";
import { Bot, FastForward, RefreshCw, Trash2, Unplug } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { datetime, num, rel, title } from "@/lib/format";
import { useSession } from "@/lib/session";
import { ErrorNote, Loading, S, Spinner, Stat, Status } from "@/components/ui";

export default function System() {
  const { data, error, loading, reload } = useApi<any>("/v1/ops/system");
  const { toast } = useSession();
  const [busy, setBusy] = useState<string | null>(null);
  const run = async (key: string, fn: () => Promise<any>, msg: (r: any) => string) => {
    setBusy(key);
    try {
      const r = await fn();
      toast(msg(r));
      reload();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(null);
    }
  };
  const advance = (h: number) => run(`adv${h}`, () => api("/v1/dev/clock/advance", { body: { hours: h } }), (r) => `Moved ${h} h forward; ran ${r.jobs_run} jobs`);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorNote error={error} />;
  const now = data.clock.now;
  return (
    <>
      <div className="page-title"><div><h1>Simulator</h1><p>Dev mode runs a simulated Instagram, YouTube and Razorpay. Move the platform clock to watch polling, the 72-hour auto-approve and settlement happen.</p></div></div>
      <div className="grid split">
        <section className="feature">
          <span style={{ color: "#d6dcc6" }}>Platform clock</span>
          <h2 className="num">{datetime(now)}</h2>
          <p>{data.clock.offset_hours ? `${Math.round(data.clock.offset_hours)} hours ahead of real time` : "In step with real time"}</p>
          <div className="row wrap-row">
            {[1, 6, 24, 72, 168].map((h) => (
              <button key={h} className="btn accent sm" disabled={!!busy} onClick={() => advance(h)}>
                {busy === `adv${h}` ? <Spinner /> : <><FastForward size={14} strokeWidth={2} /> {h < 24 ? `${h} h` : `${h / 24} d`}</>}
              </button>
            ))}
          </div>
        </section>
        <section className="card stack">
          <div className="card-head" style={{ margin: 0 }}><h2>Jobs</h2>
            <button className="btn sm on-surface" disabled={!!busy} onClick={() => run("run", () => api("/v1/dev/jobs/run", { method: "POST" }), (r) => `Ran ${r.ran} due jobs`)}><RefreshCw size={14} strokeWidth={S} /> Run due now</button></div>
          <div className="row wrap-row">{Object.entries(data.jobs).map(([k, v]: any) => <span key={k} className="tag">{title(k)} {num(v)}</span>)}</div>
          <div className="items">
            {data.next_jobs.slice(0, 6).map((j: any, i: number) => <div key={i} className="item"><span className="grow small">{j.kind}</span><span className="muted small">{rel(j.run_at, now)}</span></div>)}
          </div>
        </section>
      </div>
      <div className="grid cols-4">
        <Stat k="Posts being tracked" v={num(data.tracking)} />
        <Stat k="Held view deltas" v={num(data.held_snapshots)} d="Waiting in the trust queue" />
        <Stat k="Failed jobs" v={num(data.failed_jobs.length)} />
        <Stat k="Last reconciliation" v={data.last_reconcile ? `${data.last_reconcile.issues} issues` : "Not run"}
          d={<button className="link" style={{ border: 0, background: "none", padding: 0, cursor: "pointer" }} onClick={() => run("rec", () => api("/v1/ops/reconcile", { method: "POST" }), (r) => `Reconciled: ${r.issues} mismatches`)}>Run now</button>} />
      </div>
      <section className="card">
        <div className="card-head"><h2>Deliverables</h2><span className="muted small">Inject bought views to test the anomaly filter, or delete a post to test the freeze.</span></div>
        <div className="table-wrap"><table>
          <thead><tr><th>Post</th><th className="r">Views</th><th>Status</th><th>Next poll</th><th></th></tr></thead>
          <tbody>{data.deliverables.map((d: any) => (
            <tr key={d.id}>
              <td><strong>{d.creator}</strong><span className="sub">{d.brief}</span></td>
              <td className="r num">{num(d.views)}</td>
              <td><div className="row" style={{ gap: 6 }}><Status s={d.status} /><Status s={d.tracking_status} /></div></td>
              <td className="muted small nowrap">{d.next_poll_at ? rel(d.next_poll_at, now) : "—"}</td>
              <td className="r nowrap">
                <button className="btn sm on-surface" disabled={!!busy} onClick={() => run(`bot${d.id}`, () => api(`/v1/dev/social/deliverables/${d.id}/bot-views`, { body: { views: 1500000 } }), () => "Injected 1.5M bought views; they show at the next poll")}><Bot size={14} strokeWidth={S} /> Bot views</button>{" "}
                <button className="btn sm ghost" disabled={!!busy} onClick={() => confirm("Delete this post on the simulated platform?") && run(`del${d.id}`, () => api(`/v1/dev/social/deliverables/${d.id}/delete`, { method: "POST" }), () => "Post deleted; tracking freezes at the next poll")}><Trash2 size={14} strokeWidth={S} /></button>
              </td>
            </tr>
          ))}</tbody>
        </table></div>
      </section>
      <section className="card">
        <div className="card-head"><h2>Connected accounts</h2><span className="muted small">Revoke a token to test the reconnect flow.</span></div>
        <div className="items">
          {data.accounts.map((a: any) => (
            <div key={a.id} className="item"><span className="grow">@{a.handle} <span className="muted small">· {a.platform}</span></span><Status s={a.status} />
              <button className="btn sm ghost" disabled={!!busy || a.status !== "active"} onClick={() => run(`rev${a.id}`, () => api(`/v1/dev/social/accounts/${a.id}/revoke`, { method: "POST" }), () => "Token revoked on the simulated platform")}><Unplug size={14} strokeWidth={S} /> Revoke</button>
            </div>
          ))}
        </div>
      </section>
      {data.failed_jobs.length > 0 && (
        <section className="card"><div className="card-head"><h2>Failed jobs</h2></div>
          <div className="items">{data.failed_jobs.map((j: any, i: number) => <div key={i} className="item" style={{ display: "grid" }}><strong className="small">{j.kind}</strong><span className="muted small">{j.error}</span></div>)}</div>
        </section>
      )}
    </>
  );
}
