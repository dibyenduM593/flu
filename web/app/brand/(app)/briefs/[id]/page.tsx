"use client";

import Link from "next/link";
import { Suspense, use, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, Check, ExternalLink, Pause, Play, Star, UserCheck, X } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { cpm, date, GOAL, inr, num, pct, payLine, short, title, USAGE } from "@/lib/format";
import { useOrg } from "@/lib/org";
import { useSession } from "@/lib/session";
import { Bars } from "@/components/charts";
import { BriefEditor, fromBrief } from "@/components/BriefEditor";
import { DeliverableCard } from "@/components/DeliverableCard";
import { Empty, ErrorNote, Field, Loading, Meter, Modal, Plat, Ring, S, Spinner, Stat, Status, Tabs, Tier } from "@/components/ui";

const PART_LABEL: Record<string, string> = { score: "Creator Score", niche: "Niche fit", cpm: "Expected views vs cap", responsiveness: "Responsiveness" };

function Applicants({ brief, onChange }: { brief: any; onChange: () => void }) {
  const { data, error, loading, reload } = useApi<any>(`/v1/briefs/${brief.id}/applications`);
  const { toast } = useSession();
  const [busy, setBusy] = useState<string | null>(null);
  const [topN, setTopN] = useState(2);
  const act = async (a: any, action: "accept" | "reject" | "shortlist") => {
    setBusy(a.id + action);
    try {
      await api(`/v1/applications/${a.id}/${action}`, { method: "POST", idempotent: action === "accept" });
      toast(action === "accept" ? `${a.creator.display_name} hired. Funds reserved in escrow.` : action === "reject" ? "Declined" : "Shortlisted");
      reload();
      onChange();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(null);
    }
  };
  const acceptTop = async () => {
    setBusy("top");
    try {
      const r = await api(`/v1/briefs/${brief.id}/accept-top`, { body: { n: topN }, idempotent: true });
      toast(r.errors.length ? `Hired ${r.hired.length}. ${r.errors[0].message}` : `Hired the top ${r.hired.length}`, r.errors.length ? "error" : "ok");
      reload();
      onChange();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(null);
    }
  };
  if (loading && !data) return <Loading />;
  if (error) return <ErrorNote error={error} />;
  const open = data.data.filter((a: any) => ["applied", "shortlisted"].includes(a.status));
  return (
    <div className="stack">
      {open.length > 1 && brief.status === "live" && (
        <div className="card row wrap-row">
          <span className="grow">Ranked by 45% Creator Score, 25% niche fit, 15% expected views for the cap, 15% responsiveness.</span>
          <select className="select" style={{ width: 90 }} value={topN} onChange={(e) => setTopN(Number(e.target.value))} aria-label="How many">
            {Array.from({ length: Math.min(open.length, brief.max_creators - brief.hired_count) }, (_, i) => i + 1).map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
          <button className="btn primary" onClick={acceptTop} disabled={busy === "top"}>{busy === "top" ? <Spinner /> : `Hire the top ${topN}`}</button>
        </div>
      )}
      {!data.data.length && <div className="card"><Empty title="No applications yet">Eligible creators were notified when you published. Invite creators from the directory to move faster.</Empty></div>}
      {data.data.map((a: any, i: number) => {
        const au = a.audits[0];
        const parts = a.rank_breakdown.parts || {};
        return (
          <section key={a.id} className="card stack fade-in">
            <div className="row wrap-row" style={{ alignItems: "flex-start" }}>
              <Ring value={a.rank_score * 100} size={60} stroke={6} label={`Match ${Math.round(a.rank_score * 100)}`} />
              <div className="grow" style={{ minWidth: 200 }}>
                <div className="row wrap-row" style={{ gap: 8 }}>
                  <strong style={{ fontSize: 17 }}>{a.creator.display_name}</strong>
                  <Tier tier={a.creator.tier} />
                  <span className="muted small">Score {Math.round(a.creator.score)}</span>
                  {a.invited && <span className="tag olive">Invited</span>}
                  {i === 0 && open.includes(a) && <span className="tag lime">Top match</span>}
                </div>
                <div className="muted small">{a.creator.city} · {a.creator.niches.map(title).join(", ")}</div>
                <p style={{ marginTop: 6 }}>“{a.pitch}”</p>
              </div>
              <Status s={a.status} />
            </div>
            <div className="grid cols-4" style={{ gap: 8 }}>
              {au && [["Followers", short(au.followers)], ["Median views", short(au.median_views)], ["Engagement", pct(au.engagement_rate)],
                ["Past Flu posts", a.history?.deliverables ? `${a.history.deliverables} · ${short(a.history.median_verified_views)} views` : "First brief"]].map(([k, v]) => (
                <div key={k} className="card soft tight"><div className="muted small">{k}</div><div className="strong num">{v}</div></div>
              ))}
            </div>
            <details>
              <summary className="link" style={{ cursor: "pointer" }}>Why this rank</summary>
              <div className="stack" style={{ marginTop: 10 }}>
                {Object.entries(parts).map(([k, v]: any) => (
                  <div key={k} className="grid" style={{ gridTemplateColumns: "170px 1fr 44px", gap: 10, alignItems: "center" }}>
                    <span className="small">{PART_LABEL[k]} <span className="faint">{Math.round(a.rank_breakdown.weights[k] * 100)}%</span></span>
                    <Meter value={v} /><span className="num small muted" style={{ textAlign: "right" }}>{Math.round(v * 100)}</span>
                  </div>
                ))}
                <span className="muted small">Expected about {num(a.rank_breakdown.expected?.predicted_views)} views per post → {inr(a.rank_breakdown.expected?.per_deliverable_paise)} per post at this brief’s rate.</span>
                {a.sample_posts.length > 0 && (
                  <div className="items">
                    {a.sample_posts.map((s: any) => (
                      <a key={s.permalink} href={s.permalink} target="_blank" rel="noreferrer" className="item link-row">
                        <span className="grow ellipsis">{s.caption}</span><span className="num muted">{short(s.views)} views</span><ExternalLink size={14} />
                      </a>
                    ))}
                  </div>
                )}
              </div>
            </details>
            {["applied", "shortlisted"].includes(a.status) && brief.status === "live" && (
              <div className="row wrap-row" style={{ justifyContent: "flex-end" }}>
                <button className="btn ghost sm" onClick={() => act(a, "reject")} disabled={!!busy}><X size={14} /> Decline</button>
                {a.status === "applied" && <button className="btn sm" onClick={() => act(a, "shortlist")} disabled={!!busy}><Star size={14} strokeWidth={S} /> Shortlist</button>}
                <button className="btn primary sm" onClick={() => act(a, "accept")} disabled={!!busy}>{busy === a.id + "accept" ? <Spinner /> : <><UserCheck size={14} strokeWidth={S} /> Hire</>}</button>
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}

function ApproveModal({ d, onClose, onDone }: { d: any; onClose: () => void; onDone: () => void }) {
  const [r, setR] = useState({ brief_adherence: 5, content_quality: 5, would_book_again: true });
  const [busy, setBusy] = useState(false);
  const { toast } = useSession();
  const go = async () => {
    setBusy(true);
    try {
      await api(`/v1/deliverables/${d.id}/approve`, { body: { rating: r }, idempotent: true });
      toast("Approved. Earnings released to the creator.");
      onDone();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open onClose={onClose} title="Approve post">
      <p className="muted">Approving releases what has accrued so far; later verified views keep paying out daily until the cap or the end of the tracking window.</p>
      {(["brief_adherence", "content_quality"] as const).map((k) => (
        <Field key={k} label={k === "brief_adherence" ? "Followed the brief" : "Content quality"}>
          <div className="chips on-surface">
            {[1, 2, 3, 4, 5].map((n) => <button key={n} className="chip" aria-pressed={r[k] === n} onClick={() => setR({ ...r, [k]: n })}>{n}</button>)}
          </div>
        </Field>
      ))}
      <label className="check"><input type="checkbox" checked={r.would_book_again} onChange={(e) => setR({ ...r, would_book_again: e.target.checked })} /> I’d hire this creator again</label>
      <div className="row" style={{ justifyContent: "flex-end" }}><button className="btn ghost" onClick={onClose}>Cancel</button><button className="btn primary" onClick={go} disabled={busy}>{busy ? <Spinner /> : "Approve"}</button></div>
    </Modal>
  );
}

function DisputeModal({ d, onClose, onDone }: { d: any; onClose: () => void; onDone: () => void }) {
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<ApiError | null>(null);
  const { toast } = useSession();
  const go = async () => {
    try {
      await api(`/v1/deliverables/${d.id}/dispute`, { body: { reason, evidence_urls: [] } });
      toast("Disputed. The creator has 48 hours to respond; Flu ops decides.");
      onDone();
    } catch (e) {
      setErr(e as ApiError);
    }
  };
  return (
    <Modal open onClose={onClose} title="Dispute post">
      <p className="muted">Funds stay in escrow until Flu ops decides. Disputes need a specific reason tied to the brief.</p>
      <Field label="What’s wrong"><textarea className="textarea" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="The product is only on screen for 2 seconds; the brief asked to show it in the first 3 seconds." /></Field>
      <ErrorNote error={err} />
      <div className="row" style={{ justifyContent: "flex-end" }}><button className="btn ghost" onClick={onClose}>Cancel</button><button className="btn danger" onClick={go} disabled={reason.trim().length < 10}>Open dispute</button></div>
    </Modal>
  );
}

function Posts({ brief, onChange }: { brief: any; onChange: () => void }) {
  const { data, error, loading, reload } = useApi<any>(`/v1/briefs/${brief.id}/hires`);
  const [approve, setApprove] = useState<any>(null);
  const [dispute, setDispute] = useState<any>(null);
  const done = () => { setApprove(null); setDispute(null); reload(); onChange(); };
  if (loading && !data) return <Loading />;
  if (error) return <ErrorNote error={error} />;
  if (!data.data.length) return <div className="card"><Empty title="No one hired yet">Hire from the Applicants tab; each hire reserves that creator’s maximum payout.</Empty></div>;
  return (
    <div className="stack-lg">
      {data.data.map((h: any) => (
        <section key={h.id} className="card stack">
          <div className="row between wrap-row">
            <div className="row"><div className="avatar">{h.creator.display_name.split(" ").map((w: string) => w[0]).join("")}</div>
              <div><strong>{h.creator.display_name}</strong><div className="muted small">{h.creator.accounts.map((a: any) => `@${a.handle}`).join(" · ")} · <Tier tier={h.creator.tier} /></div></div></div>
            <div className="row"><span className="muted small num">{inr(h.reserved_paise)} reserved</span><Status s={h.status} />{!h.contract?.creator_accepted_at && h.status === "active" && <span className="tag warn">Contract unsigned</span>}</div>
          </div>
          {h.deliverables.length === 0 && <p className="muted small">No post yet ({h.deliverables_expected} expected{brief.deadline ? ` by ${date(brief.deadline)}` : ""}).</p>}
          {h.deliverables.map((d: any) => (
            <DeliverableCard key={d.id} d={d} actions={d.status === "submitted" && (
              <div className="row">
                <button className="btn sm ghost" onClick={() => setDispute(d)}>Dispute</button>
                <button className="btn sm primary" onClick={() => setApprove(d)}><Check size={14} strokeWidth={2} /> Approve</button>
              </div>
            )} />
          ))}
        </section>
      ))}
      {approve && <ApproveModal d={approve} onClose={() => setApprove(null)} onDone={done} />}
      {dispute && <DisputeModal d={dispute} onClose={() => setDispute(null)} onDone={done} />}
    </div>
  );
}

function Performance({ brief }: { brief: any }) {
  const { data, error, loading } = useApi<any>(`/v1/briefs/${brief.id}/performance`);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorNote error={error} />;
  const t = data.totals;
  return (
    <div className="stack-lg">
      <div className="grid cols-4">
        <Stat k="Verified views" v={num(t.verified_views)} d={`${t.deliverables} post${t.deliverables === 1 ? "" : "s"}`} />
        <Stat k="Cost to date" v={inr(t.cost_paise)} d="Excludes fee and GST" />
        <Stat k="Effective CPM" v={t.cpm_paise ? inr(t.cpm_paise, { decimals: true }) : "—"} d={`Brief rate ${brief.cpm_paise ? inr(brief.cpm_paise, { decimals: true }) : "flat"}`} />
        <Stat k="Projected spend" v={inr(t.projected_paise)} d="At each creator’s median views" />
      </div>
      {data.daily.length > 0 && (
        <section className="card"><div className="card-head"><h2>Verified views by day</h2></div>
          <Bars values={data.daily.map((d: any) => d.views)} labels={data.daily.map((d: any) => date(d.date))} label="Verified views by day" />
        </section>
      )}
      <section className="card">
        <div className="card-head"><h2>By creator</h2><span className="muted small">Refreshed every 6 hours</span></div>
        {data.rows.length ? (
          <div className="table-wrap"><table>
            <thead><tr><th>Creator</th><th className="r">Verified views</th><th className="r">Engagement</th><th className="r">Cost</th><th className="r">CPM</th><th>Status</th></tr></thead>
            <tbody>{data.rows.map((r: any) => (
              <tr key={r.deliverable.id}>
                <td><strong>{r.creator.display_name}</strong><span className="sub"><a href={r.deliverable.post_url} target="_blank" rel="noreferrer" className="link">@{r.deliverable.handle} <ExternalLink size={11} /></a></span></td>
                <td className="r num">{num(r.verified_views)}</td><td className="r num">{pct(r.engagement_rate)}</td>
                <td className="r num">{inr(r.cost_paise)}</td><td className="r num">{r.cpm_paise ? inr(r.cpm_paise, { decimals: true }) : "—"}</td>
                <td><Status s={r.deliverable.status} /></td>
              </tr>
            ))}</tbody>
          </table></div>
        ) : <Empty title="No posts yet" />}
      </section>
    </div>
  );
}

function Details({ brief, reload }: { brief: any; reload: () => void }) {
  const org = useOrg();
  const orgInfo = useApi<any>(org ? `/v1/orgs/${org.id}` : null);
  const wallet = useApi<any>(org ? `/v1/orgs/${org.id}/wallet` : null);
  const { toast } = useSession();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  const editable = ["draft", "paused"].includes(brief.status);
  if (editable && orgInfo.data && wallet.data) {
    const save = async (payload: any, publish: boolean) => {
      setBusy(true);
      setErr(null);
      try {
        await api(`/v1/briefs/${brief.id}`, { method: "PATCH", body: payload });
        if (publish) await api(`/v1/briefs/${brief.id}/publish`, { method: "POST" });
        toast(publish ? "Published" : "Saved");
        reload();
      } catch (e) {
        setErr(e as ApiError);
      } finally {
        setBusy(false);
      }
    };
    return <BriefEditor initial={fromBrief(brief)} takeRate={orgInfo.data.take_rate} available={wallet.data.summary.available_paise} onSave={save} saving={busy} error={err} />;
  }
  const req = brief.required_elements || {};
  return (
    <div className="grid split">
      <section className="card stack">
        <p className="lead">{brief.product}</p>
        <div className="kv">
          <div><span className="k">Goal</span><span>{GOAL[brief.goal]}</span></div>
          <div><span className="k">Pay</span><span>{payLine(brief)}</span></div>
          <div><span className="k">Posts per creator</span><span>{brief.deliverables_per_creator}</span></div>
          <div><span className="k">Usage rights</span><span>{USAGE[brief.usage_rights]}</span></div>
          <div><span className="k">Views counted for</span><span>{brief.tracking_days} days</span></div>
          <div><span className="k">Required</span><span>{[req.mention, ...(req.hashtags || []), req.discount_code].filter(Boolean).join(" ")}</span></div>
          <div><span className="k">Niches</span><span>{brief.niches.map(title).join(", ") || "Any"}</span></div>
          <div><span className="k">Cities</span><span>{brief.cities.join(", ") || "Any"}</span></div>
        </div>
        {brief.status === "live" && <p className="muted small">Pause the brief to edit it.</p>}
      </section>
      <section className="card stack">
        <h2 style={{ fontSize: 18, fontWeight: 600 }}>Angles</h2>
        {brief.angles.map((a: any) => <div key={a.id} className="angle"><div className="hook">“{a.hook}”</div><div className="muted small">{a.title}{a.format ? ` · ${a.format}` : ""}</div></div>)}
      </section>
    </div>
  );
}

function BriefPage({ id }: { id: string }) {
  const params = useSearchParams();
  const router = useRouter();
  const { toast } = useSession();
  const { data: b, error, loading, reload } = useApi<any>(`/v1/briefs/${id}`);
  const [tab, setTabState] = useState<string>(params.get("tab") || "applicants");
  const setTab = (t: string) => { setTabState(t); router.replace(`/brand/briefs/${id}?tab=${t}`, { scroll: false }); };
  const [busy, setBusy] = useState(false);
  if (loading && !b) return <Loading />;
  if (error) return <ErrorNote error={error} />;
  const status = async (s: string) => {
    setBusy(true);
    try {
      if (s === "publish") await api(`/v1/briefs/${id}/publish`, { method: "POST" });
      else await api(`/v1/briefs/${id}/status`, { body: { status: s } });
      toast(s === "publish" ? "Published" : `Brief ${s}`);
      reload();
    } catch (e: any) {
      toast(e.message + ((e.details?.issues || []).length ? `: ${e.details.issues.join(", ")}` : ""), "error");
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <Link href="/brand/briefs" className="link"><ArrowLeft size={15} /> Briefs</Link>
      <div className="page-title">
        <div>
          <div className="row" style={{ gap: 8 }}><Status s={b.status} />{b.platforms.map((p: string) => <Plat key={p} p={p} />)}<Tier tier={b.min_tier} /></div>
          <h1 style={{ marginTop: 6 }}>{b.title}</h1>
          <p>{payLine(b)} · {b.hired_count} of {b.max_creators} hired · {inr(b.reserve_per_creator_paise)} reserved per creator</p>
        </div>
        <div className="row">
          {["draft", "paused"].includes(b.status) && <button className="btn primary" disabled={busy} onClick={() => status("publish")}><Play size={15} strokeWidth={S} /> {b.status === "draft" ? "Publish" : "Resume"}</button>}
          {b.status === "live" && <button className="btn" disabled={busy} onClick={() => status("paused")}><Pause size={15} strokeWidth={S} /> Pause</button>}
          {b.status !== "closed" && <button className="btn ghost" disabled={busy} onClick={() => confirm("Close this brief? Hired creators can still finish.") && status("closed")}>Close</button>}
        </div>
      </div>
      {b.policy_flags?.length > 0 && <div className="note bad">Policy pre-check: {b.policy_flags.join(" · ")}</div>}
      <Tabs value={tab} onChange={setTab} items={[
        { id: "applicants", label: "Applicants", count: b.application_count }, { id: "posts", label: "Hired and posts", count: b.hired_count },
        { id: "performance", label: "Performance" }, { id: "brief", label: "Brief" },
      ]} />
      {tab === "applicants" && <Applicants brief={b} onChange={reload} />}
      {tab === "posts" && <Posts brief={b} onChange={reload} />}
      {tab === "performance" && <Performance brief={b} />}
      {tab === "brief" && <Details brief={b} reload={reload} />}
    </>
  );
}

export default function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <Suspense><BriefPage id={id} /></Suspense>;
}
