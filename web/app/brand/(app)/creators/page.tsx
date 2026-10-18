"use client";

import { useState } from "react";
import { ExternalLink, Search, Send } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { CITIES, NICHES, short, title } from "@/lib/format";
import { useOrg } from "@/lib/org";
import { useSession } from "@/lib/session";
import { Empty, ErrorNote, Field, Loading, Modal, Plat, Ring, S, Tier } from "@/components/ui";

export default function Creators() {
  const org = useOrg();
  const { toast } = useSession();
  const [f, setF] = useState({ q: "", niche: "", tier: "", city: "", platform: "" });
  const qs = new URLSearchParams(Object.entries(f).filter(([, v]) => v) as any).toString();
  const { data, error, loading } = useApi<any>(`/v1/directory/creators?${qs}`);
  const briefs = useApi<any>(org ? `/v1/orgs/${org.id}/briefs` : null);
  const [picked, setPicked] = useState<any>(null);
  const [briefId, setBriefId] = useState("");
  const live = (briefs.data?.data || []).filter((b: any) => b.status === "live");
  const invite = async () => {
    try {
      const r = await api(`/v1/briefs/${briefId}/invites`, { body: { creator_ids: [picked.id] } });
      toast(r.invited ? `Invited ${picked.display_name}` : "Already invited, or your plan’s invite limit is reached");
      setPicked(null);
    } catch (e: any) {
      toast(e.message, "error");
    }
  };
  const sel = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLSelectElement | HTMLInputElement>) => setF({ ...f, [k]: e.target.value });
  return (
    <>
      <div className="page-title"><div><h1>Creators</h1><p>Every creator here connected their account and passed the audit. Ranked by Creator Score.</p></div></div>
      <div className="grid filters">
        <div className="input-wrap"><Search size={17} strokeWidth={S} /><input className="input on-ground" placeholder="Search by name or handle" value={f.q} onChange={sel("q")} /></div>
        <select className="select" style={{ background: "var(--surface)" }} value={f.niche} onChange={sel("niche")} aria-label="Niche"><option value="">All niches</option>{NICHES.map((n) => <option key={n} value={n}>{title(n)}</option>)}</select>
        <select className="select" style={{ background: "var(--surface)" }} value={f.tier} onChange={sel("tier")} aria-label="Tier"><option value="">Any tier</option>{["silver", "gold", "platinum"].map((t) => <option key={t} value={t}>{title(t)} and up</option>)}</select>
        <select className="select" style={{ background: "var(--surface)" }} value={f.city} onChange={sel("city")} aria-label="City"><option value="">Any city</option>{CITIES.map((c) => <option key={c}>{c}</option>)}</select>
        <select className="select" style={{ background: "var(--surface)" }} value={f.platform} onChange={sel("platform")} aria-label="Platform"><option value="">Both platforms</option><option value="instagram">Instagram</option><option value="youtube">YouTube</option></select>
      </div>
      <ErrorNote error={error} />
      {loading && !data ? <Loading /> : data?.data.length ? (
        <div className="grid cols-3">
          {data.data.map((c: any) => (
            <section key={c.id} className="card stack fade-in">
              <div className="row">
                <Ring value={c.score} size={56} stroke={6} />
                <div className="grow">
                  <strong>{c.display_name}</strong>
                  <div className="row" style={{ gap: 8 }}><Tier tier={c.tier} /><span className="muted small">{c.city}</span></div>
                </div>
              </div>
              <div className="tags">{c.niches.map((n: string) => <span key={n} className="tag">{title(n)}</span>)}</div>
              <div className="stack" style={{ gap: 4 }}>
                {c.accounts.map((a: any) => <Plat key={a.platform} p={a.platform}>@{a.handle} · {short(a.followers)}</Plat>)}
              </div>
              <div className="grid cols-2" style={{ gap: 8 }}>
                <div className="card soft tight"><div className="muted small">Median views</div><div className="strong num">{short(c.median_views)}</div></div>
                <div className="card soft tight"><div className="muted small">Flu posts</div><div className="strong num">{c.flu_history.deliverables || "None yet"}</div></div>
              </div>
              {c.sample_posts[0] && (
                <a href={c.sample_posts[0].permalink} target="_blank" rel="noreferrer" className="item link-row">
                  <span className="grow ellipsis small">{c.sample_posts[0].caption}</span><span className="num small muted">{short(c.sample_posts[0].views)}</span><ExternalLink size={13} />
                </a>
              )}
              <button className="btn" onClick={() => { setPicked(c); setBriefId(live[0]?.id || ""); }}><Send size={15} strokeWidth={S} /> Invite to a brief</button>
            </section>
          ))}
        </div>
      ) : <div className="card"><Empty title="No creators match these filters" /></div>}
      <Modal open={!!picked} onClose={() => setPicked(null)} title={`Invite ${picked?.display_name ?? ""}`}>
        {live.length ? (
          <>
            <Field label="Brief">
              <select className="select" value={briefId} onChange={(e) => setBriefId(e.target.value)}>{live.map((b: any) => <option key={b.id} value={b.id}>{b.title}</option>)}</select>
            </Field>
            <p className="muted small">They get a push and WhatsApp message with the brief. They still need to meet its tier and niche to apply.</p>
            <div className="row" style={{ justifyContent: "flex-end" }}><button className="btn primary" onClick={invite} disabled={!briefId}>Send invite</button></div>
          </>
        ) : <Empty title="Publish a brief first" />}
      </Modal>
    </>
  );
}
