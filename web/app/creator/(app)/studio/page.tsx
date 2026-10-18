"use client";

import { useState } from "react";
import { ExternalLink, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import { useApi, useJob } from "@/lib/hooks";
import { date, NICHES, num, pct, short, title } from "@/lib/format";
import { useSession } from "@/lib/session";
import { DiagnosisView, HookCard } from "@/components/creator";
import { Empty, ErrorNote, Field, Loading, Meter, Modal, Plat, S, Spinner, Tabs } from "@/components/ui";

function Posts() {
  const { data, error, loading, reload } = useApi<any>("/v1/creator/media");
  const { toast } = useSession();
  const [jobId, setJobId] = useState<string | null>(null);
  const job = useJob(jobId);
  const diagnose = async (m: any) => {
    if (m.diagnosis_job_id) return setJobId(m.diagnosis_job_id);
    try {
      const r = await api(`/v1/creator/media/${m.id}/diagnose`, { method: "POST" });
      setJobId(r.job_id);
      reload();
    } catch (e: any) {
      toast(e.message, "error");
    }
  };
  if (loading && !data) return <Loading />;
  if (error) return <ErrorNote error={error} />;
  const rows = data.data;
  if (!rows.length) return <div className="card"><Empty title="No posts yet">Connect an account and your last 30 posts appear here.</Empty></div>;
  const medianViews = [...rows].map((m: any) => m.metrics?.views || 0).sort((a, b) => a - b)[Math.floor(rows.length / 2)];
  return (
    <section className="card">
      <div className="card-head"><h2>Your posts</h2><span className="muted small">Median {short(medianViews)} views</span></div>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Post</th><th className="r">Views</th><th className="r">Reach</th><th className="r">Engagement</th><th className="r">Length</th><th></th></tr></thead>
          <tbody>
            {rows.map((m: any) => {
              const x = m.metrics || {};
              const eng = ((x.likes || 0) + (x.comments || 0) + (x.saves || 0) + (x.shares || 0)) / Math.max(x.reach || 1, 1);
              return (
                <tr key={m.id}>
                  <td style={{ maxWidth: 380 }}>
                    <div className="ellipsis strong" style={{ fontWeight: 500 }}>{m.caption}</div>
                    <span className="sub row" style={{ gap: 8 }}><Plat p={m.platform}>{date(m.posted_at)}</Plat>{m.is_deliverable && <span className="tag olive">Brief post</span>}
                      <a href={m.permalink} target="_blank" rel="noreferrer" aria-label="Open post"><ExternalLink size={13} /></a></span>
                  </td>
                  <td className="r num">
                    <span style={{ color: (x.views || 0) >= medianViews ? "var(--good)" : undefined }}>{short(x.views)}</span>
                  </td>
                  <td className="r num">{short(x.reach)}</td>
                  <td className="r num">{pct(eng)}</td>
                  <td className="r num">{m.duration_s ? `${m.duration_s} s` : "—"}</td>
                  <td className="r"><button className="btn sm on-surface" onClick={() => diagnose(m)}><Sparkles size={14} strokeWidth={S} />{m.diagnosis_job_id ? "View diagnosis" : "Diagnose"}</button></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <Modal open={!!jobId} onClose={() => setJobId(null)} title="Post diagnosis"><DiagnosisView job={job} /></Modal>
    </section>
  );
}

function Hooks() {
  const { toast } = useSession();
  const hires = useApi<any>("/v1/creator/hires");
  const apps = useApi<any>("/v1/creator/applications");
  const history = useApi<any>("/v1/creator/hooks");
  const [briefId, setBriefId] = useState("");
  const [niche, setNiche] = useState("");
  const [product, setProduct] = useState("");
  const [busy, setBusy] = useState(false);
  const [fresh, setFresh] = useState<any[] | null>(null);
  const briefs = new Map<string, string>();
  hires.data?.data.forEach((h: any) => briefs.set(h.brief.id, h.brief.title));
  apps.data?.data.forEach((a: any) => briefs.set(a.brief.id, a.brief.title));
  const go = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await api("/v1/creator/hooks", { body: { brief_id: briefId || null, niche: niche || null, product: product || null } });
      setFresh(r.hooks);
      history.reload();
    } catch (er: any) {
      toast(er.message, "error");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="grid split-r">
      <form className="card form" onSubmit={go}>
        <h2 style={{ fontSize: 18, fontWeight: 600 }}>Hook generator</h2>
        <p className="muted small">Five openers, one per pattern: question, contrarian, number, POV, before/after. Mark the one you use when you submit, and your score learns from it.</p>
        <Field label="For a brief">
          <select className="select" value={briefId} onChange={(e) => setBriefId(e.target.value)}>
            <option value="">No brief, my own content</option>
            {[...briefs].map(([id, t]) => <option key={id} value={id}>{t}</option>)}
          </select>
        </Field>
        {!briefId && (
          <div className="form-row">
            <Field label="Niche">
              <select className="select" value={niche} onChange={(e) => setNiche(e.target.value)}>
                <option value="">My main niche</option>
                {NICHES.map((n) => <option key={n} value={n}>{title(n)}</option>)}
              </select>
            </Field>
            <Field label="Product or topic"><input className="input" value={product} onChange={(e) => setProduct(e.target.value)} placeholder="sunscreen" /></Field>
          </div>
        )}
        <button className="btn primary" disabled={busy}>{busy ? <Spinner /> : <><Sparkles size={16} strokeWidth={S} /> Write 5 hooks</>}</button>
      </form>
      <div className="stack">
        {(fresh || history.data?.data || []).slice(0, fresh ? 5 : 10).map((h: any) => <HookCard key={h.id} h={h} onCopy={() => toast("Copied")} />)}
        {!fresh && !history.data?.data?.length && <div className="card"><Empty title="Your hooks show up here" /></div>}
      </div>
    </div>
  );
}

function Schedule() {
  const { data, error, loading } = useApi<any>("/v1/creator/schedule");
  if (loading && !data) return <Loading />;
  if (error) return <ErrorNote error={error} />;
  const hours = Object.entries(data.hour_scores as Record<string, number>);
  const max = Math.max(...hours.map(([, v]) => v), 0.01);
  return (
    <div className="grid split-r">
      <section className="card stack">
        <h2 style={{ fontSize: 18, fontWeight: 600 }}>Best times to post</h2>
        <p className="muted small">From {data.source}. Times are IST.</p>
        <div className="row wrap-row">{data.top_hours_ist.map((h: number) => <span key={h} className="tag lime" style={{ height: 32, fontSize: 15, padding: "0 14px" }}>{fmtHour(h)}</span>)}</div>
        <div className="items">
          {data.slots.map((s: any, i: number) => (
            <div key={i} className="item"><span className="grow">{s.weekday}, {date(s.date)}</span><strong className="num">{fmtHour(s.hour_ist)}</strong></div>
          ))}
        </div>
      </section>
      <section className="card stack">
        <h2 style={{ fontSize: 18, fontWeight: 600 }}>Your audience by hour</h2>
        {hours.map(([h, v]) => (
          <div key={h} className="row" style={{ gap: 10 }}>
            <span className="num small muted" style={{ width: 52 }}>{fmtHour(Number(h))}</span>
            <div className="grow"><Meter value={v / max} lime={data.top_hours_ist.includes(Number(h))} /></div>
          </div>
        ))}
      </section>
    </div>
  );
}

const fmtHour = (h: number) => `${((h + 11) % 12) + 1} ${h < 12 ? "am" : "pm"}`;

export default function Studio() {
  const [tab, setTab] = useState<"posts" | "hooks" | "schedule">("posts");
  return (
    <>
      <div className="page-title"><div><h1>Studio</h1><p>Find out why a post flopped, write better openers, and post when your audience is online.</p></div></div>
      <Tabs value={tab} onChange={setTab} items={[{ id: "posts", label: "Posts and diagnosis" }, { id: "hooks", label: "Hooks" }, { id: "schedule", label: "Posting times" }]} />
      {tab === "posts" && <Posts />}
      {tab === "hooks" && <Hooks />}
      {tab === "schedule" && <Schedule />}
    </>
  );
}
