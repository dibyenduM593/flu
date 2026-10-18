"use client";

import Link from "next/link";
import { use, useState } from "react";
import { ArrowLeft, Check, Lock, Sparkles, X } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { date, GOAL, inr, num, PAY_MODEL, payLine, title, USAGE } from "@/lib/format";
import { useSession } from "@/lib/session";
import { HookCard } from "@/components/creator";
import { ErrorNote, Field, Loading, Plat, S, Spinner, Status, Tier } from "@/components/ui";

export default function BriefDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: b, error, loading, reload } = useApi<any>(`/v1/briefs/${id}`);
  const { toast } = useSession();
  const [pitch, setPitch] = useState("");
  const [sample, setSample] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  const [hooks, setHooks] = useState<any[] | null>(null);
  const [hookBusy, setHookBusy] = useState(false);

  if (loading && !b) return <Loading />;
  if (error) return <ErrorNote error={error} />;

  const apply = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await api(`/v1/briefs/${id}/applications`, { body: { pitch, sample_url: sample || null } });
      toast("Applied. The brand sees you ranked by your Creator Score and fit.");
      reload();
    } catch (e) {
      setErr(e as ApiError);
    } finally {
      setBusy(false);
    }
  };

  const genHooks = async () => {
    setHookBusy(true);
    try {
      const r = await api("/v1/creator/hooks", { body: { brief_id: id } });
      setHooks(r.hooks);
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setHookBusy(false);
    }
  };

  const req = b.required_elements || {};
  return (
    <>
      <Link href="/creator/briefs" className="link"><ArrowLeft size={15} /> All briefs</Link>
      <div className="grid split">
        <div className="stack-lg">
          <section className="card stack-lg">
            <div className="row">
              <div className="avatar square lg">{b.org.name.split(" ").map((w: string) => w[0]).join("").slice(0, 2)}</div>
              <div className="grow">
                <div className="muted">{b.org.name}{b.org.verified && " · GST verified"}</div>
                <h1 style={{ fontSize: 26, fontWeight: 600 }}>{b.title}</h1>
              </div>
            </div>
            <p className="lead">{b.product}</p>
            <div className="tags">
              {b.platforms.map((p: string) => <span key={p} className="tag"><Plat p={p} /></span>)}
              <span className="tag">{GOAL[b.goal]}</span>
              <span className="tag">{b.deliverables_per_creator} × {b.deliverable_type === "reel" ? "Reel" : "Short"}</span>
              <span className="tag">{USAGE[b.usage_rights]}</span>
              {b.niches.map((n: string) => <span key={n} className="tag">{title(n)}</span>)}
            </div>
          </section>

          {b.angles.length > 0 && (
            <section className="card">
              <div className="card-head"><h2>Angles the brand suggests</h2></div>
              <div className="stack">
                {b.angles.map((a: any) => (
                  <div key={a.id} className="angle">
                    <div className="row between"><span className="tag olive">{a.format || "angle"}</span>{a.length_s && <span className="faint small">{a.length_s} s</span>}</div>
                    <div className="hook">“{a.hook}”</div>
                    {a.why_now && <div className="muted small">{a.why_now}</div>}
                  </div>
                ))}
              </div>
            </section>
          )}

          <section className="card">
            <div className="card-head"><h2>What your post must include</h2></div>
            <div className="items">
              {req.mention && <div className="item"><Check size={16} strokeWidth={2} color="var(--good)" /><span className="grow">Mention <strong>{req.mention}</strong> in the caption</span></div>}
              {(req.hashtags || []).map((h: string) => <div key={h} className="item"><Check size={16} strokeWidth={2} color="var(--good)" /><span className="grow">Hashtag <strong>{h}</strong></span></div>)}
              <div className="item"><Check size={16} strokeWidth={2} color="var(--good)" /><span className="grow">An ad disclosure: #ad, #collab or the paid-partnership label (ASCI)</span></div>
              {req.discount_code && <div className="item"><Check size={16} strokeWidth={2} color="var(--good)" /><span className="grow">Discount code <strong>{req.discount_code}</strong></span></div>}
              {req.link_in_bio && <div className="item"><Check size={16} strokeWidth={2} color="var(--good)" /><span className="grow">Product link in your bio while the post is live</span></div>}
            </div>
            {(b.dos.length > 0 || b.donts.length > 0) && (
              <div className="grid cols-2" style={{ marginTop: 14 }}>
                <div className="stack" style={{ gap: 6 }}>
                  <span className="muted small">Do</span>
                  {b.dos.map((x: string) => <div key={x} className="row" style={{ alignItems: "flex-start", gap: 8 }}><Check size={15} strokeWidth={2} style={{ marginTop: 3 }} />{x}</div>)}
                </div>
                <div className="stack" style={{ gap: 6 }}>
                  <span className="muted small">Don’t</span>
                  {b.donts.map((x: string) => <div key={x} className="row" style={{ alignItems: "flex-start", gap: 8 }}><X size={15} strokeWidth={2} style={{ marginTop: 3 }} />{x}</div>)}
                </div>
              </div>
            )}
          </section>
        </div>

        <aside className="stack-lg">
          <section className="card stack">
            <span className="muted small">You could earn</span>
            <div className="big-number">{inr(b.expected.total_paise)}</div>
            <p className="muted small">At your median of {num(b.expected.predicted_views)} views. {PAY_MODEL[b.pay_model]}: {payLine(b)}.</p>
            <div className="kv small">
              <div><span className="k">Paid out</span><span>On approval, then daily as views verify</span></div>
              <div><span className="k">Approval</span><span>72 h, then automatic</span></div>
              <div><span className="k">Views counted for</span><span>{b.tracking_days} days</span></div>
              <div><span className="k">Minimum tier</span><Tier tier={b.min_tier} /></div>
              <div><span className="k">Deadline</span><span>{b.deadline ? date(b.deadline) : "Open"}</span></div>
              <div><span className="k">Slots</span><span className="num">{b.hired_count} of {b.max_creators} filled</span></div>
            </div>
          </section>

          {b.application ? (
            <section className="card stack">
              <div className="row between"><h2 style={{ fontSize: 18, fontWeight: 600 }}>Your application</h2><Status s={b.application.status} /></div>
              <p className="muted">“{b.application.pitch}”</p>
              {b.application.status === "accepted" && <Link className="btn primary" href="/creator/work">Go to the contract</Link>}
            </section>
          ) : b.eligible ? (
            <form className="card form" onSubmit={apply}>
              <h2 style={{ fontSize: 18, fontWeight: 600 }}>Apply</h2>
              <Field label="One-line pitch" hint="Why your audience fits. Brands read this next to your score." htmlFor="pitch">
                <textarea id="pitch" className="textarea" maxLength={280} value={pitch} onChange={(e) => setPitch(e.target.value)}
                  placeholder="My night-routine Reels get 2x my median views; I’ll do a day 1 vs day 14." />
              </Field>
              <Field label="Sample post (optional)" htmlFor="sample">
                <input id="sample" className="input" placeholder="https://www.instagram.com/reel/…" value={sample} onChange={(e) => setSample(e.target.value)} />
              </Field>
              <ErrorNote error={err} />
              <button className="btn primary" disabled={busy || pitch.trim().length < 5}>{busy ? <Spinner /> : "Send application"}</button>
            </form>
          ) : (
            <section className="card stack">
              <div className="row"><Lock size={18} strokeWidth={S} /><h2 style={{ fontSize: 18, fontWeight: 600 }}>Not open to you yet</h2></div>
              <div className="items">{b.locked_reasons.map((r: string) => <div key={r} className="item">{r}</div>)}</div>
              <Link href="/creator/score" className="btn">See how to move up a tier</Link>
            </section>
          )}

          <section className="card stack">
            <div className="row between"><h2 style={{ fontSize: 18, fontWeight: 600 }}>Hooks for this brief</h2></div>
            <p className="muted small">Five openers in different patterns, checked against lines already given to other creators on this brief.</p>
            {hooks ? hooks.map((h) => <HookCard key={h.id} h={h} onCopy={() => toast("Copied")} />) : (
              <button className="btn" onClick={genHooks} disabled={hookBusy}>{hookBusy ? <Spinner /> : <><Sparkles size={16} strokeWidth={S} /> Write 5 hooks</>}</button>
            )}
          </section>
        </aside>
      </div>
    </>
  );
}
