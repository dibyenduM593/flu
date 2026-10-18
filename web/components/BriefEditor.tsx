"use client";

import { useMemo, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { ApiError } from "@/lib/api";
import { inr, NICHES, title } from "@/lib/format";
import { Chips, ErrorNote, Field, S, Spinner } from "./ui";

export type BriefForm = {
  title: string; product: string; goal: string; platforms: string[]; deliverable_type: string; deliverables_per_creator: number;
  pay_model: string; cpm: string; flat: string; cap: string; min_tier: string; niches: string[]; cities: string;
  max_creators: number; deadline: string; usage_rights: string; tracking_days: number;
  mention: string; hashtags: string; discount_code: string; link_in_bio: boolean; dos: string; donts: string;
  angles: { title: string; hook: string; format: string; why_now: string; trend_ref?: string; length_s?: number; source?: string }[];
  ai_draft_id?: string | null;
};

const rupees = (paise?: number) => (paise ? String(Math.round(paise) / 100) : "");
const paise = (r: string) => Math.round((parseFloat(r || "0") || 0) * 100);

export function fromBrief(b: any): BriefForm {
  const req = b.required_elements || {};
  return {
    title: b.title || "", product: b.product || "", goal: b.goal || "awareness", platforms: b.platforms || ["instagram"],
    deliverable_type: b.deliverable_type || "reel", deliverables_per_creator: b.deliverables_per_creator || 1,
    pay_model: b.pay_model || "cpm", cpm: rupees(b.cpm_paise), flat: rupees(b.flat_paise), cap: rupees(b.cap_paise),
    min_tier: b.min_tier || "bronze", niches: b.niches || [], cities: (b.cities || []).join(", "), max_creators: b.max_creators || 5,
    deadline: b.deadline ? String(b.deadline).slice(0, 10) : "", usage_rights: b.usage_rights || "organic", tracking_days: b.tracking_days || 30,
    mention: req.mention || "", hashtags: (req.hashtags || ["#ad"]).join(" "), discount_code: req.discount_code || "",
    link_in_bio: !!req.link_in_bio, dos: (b.dos || []).join("\n"), donts: (b.donts || []).join("\n"),
    angles: (b.angles || []).map((a: any) => ({ title: a.title, hook: a.hook, format: a.format || "", why_now: a.why_now || a.angle_text || "", trend_ref: a.trend_ref, length_s: a.length_s, source: a.source })),
    ai_draft_id: b.ai_draft_id,
  };
}

export function toPayload(f: BriefForm) {
  return {
    title: f.title, product: f.product, goal: f.goal, platforms: f.platforms, deliverable_type: f.deliverable_type,
    deliverables_per_creator: Number(f.deliverables_per_creator), pay_model: f.pay_model,
    cpm_paise: f.pay_model === "flat" ? 0 : paise(f.cpm), flat_paise: f.pay_model === "cpm" ? 0 : paise(f.flat),
    cap_paise: f.pay_model === "flat" ? 0 : paise(f.cap), min_tier: f.min_tier, niches: f.niches,
    cities: f.cities.split(",").map((c) => c.trim()).filter(Boolean), max_creators: Number(f.max_creators),
    deadline: f.deadline ? new Date(f.deadline + "T23:59:00+05:30").toISOString() : null, usage_rights: f.usage_rights,
    tracking_days: Number(f.tracking_days),
    required_elements: { mention: f.mention || null, hashtags: f.hashtags.split(/[\s,]+/).filter(Boolean), disclosure: true,
      discount_code: f.discount_code || null, link_in_bio: f.link_in_bio },
    dos: f.dos.split("\n").map((s) => s.trim()).filter(Boolean), donts: f.donts.split("\n").map((s) => s.trim()).filter(Boolean),
    angles: f.angles.filter((a) => a.hook.trim()), ai_draft_id: f.ai_draft_id || null,
  };
}

export function BriefEditor({ initial, takeRate, available, onSave, saving, error }: {
  initial: BriefForm; takeRate: number; available: number;
  onSave: (payload: any, publish: boolean) => void; saving: boolean; error: ApiError | null;
}) {
  const [f, setF] = useState<BriefForm>(initial);
  const set = <K extends keyof BriefForm>(k: K, v: BriefForm[K]) => setF({ ...f, [k]: v });
  const inp = (k: keyof BriefForm) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => set(k, e.target.value as any);

  const money = useMemo(() => {
    const p = toPayload(f);
    const cap = p.pay_model === "flat" ? p.flat_paise : Math.max(p.cap_paise, p.flat_paise);
    const gross = cap * p.deliverables_per_creator;
    const per = gross + Math.round(Math.round(gross * takeRate) * 0.18);
    return { per, total: per * p.max_creators, cap };
  }, [f, takeRate]);

  return (
    <div className="grid split">
      <div className="stack-lg">
        <section className="card form">
          <h2 style={{ fontSize: 18, fontWeight: 600 }}>The brief</h2>
          <Field label="Title"><input className="input" value={f.title} onChange={inp("title")} /></Field>
          <Field label="Product, price and where it ships"><textarea className="textarea" value={f.product} onChange={inp("product")} /></Field>
          <div className="form-row three">
            <Field label="Goal">
              <select className="select" value={f.goal} onChange={inp("goal")}>
                <option value="awareness">Awareness</option><option value="installs">App installs</option><option value="orders">Orders</option>
              </select>
            </Field>
            <Field label="Format">
              <select className="select" value={f.deliverable_type} onChange={inp("deliverable_type")}>
                <option value="reel">Reel</option><option value="short">Short</option>
              </select>
            </Field>
            <Field label="Posts per creator"><input className="input" type="number" min={1} max={5} value={f.deliverables_per_creator} onChange={inp("deliverables_per_creator")} /></Field>
          </div>
          <Field label="Platforms">
            <div className="chips">
              {["instagram", "youtube"].map((p) => (
                <button type="button" key={p} className="chip" style={{ background: f.platforms.includes(p) ? undefined : "var(--surface-2)" }} aria-pressed={f.platforms.includes(p)}
                  onClick={() => set("platforms", f.platforms.includes(p) ? f.platforms.filter((x) => x !== p) : [...f.platforms, p])}>
                  {p === "instagram" ? "Instagram Reels" : "YouTube Shorts"}
                </button>
              ))}
            </div>
          </Field>
        </section>

        <section className="card form">
          <h2 style={{ fontSize: 18, fontWeight: 600 }}>Angles</h2>
          <p className="muted small">Creators see these as starting points. Edit freely; the difference from the AI draft is logged to improve future drafts.</p>
          {f.angles.map((a, i) => (
            <div key={i} className="angle">
              <div className="row between">
                <input className="input" style={{ background: "var(--surface)", height: 38, maxWidth: 240 }} value={a.title} placeholder="Angle name"
                  onChange={(e) => set("angles", f.angles.map((x, j) => (j === i ? { ...x, title: e.target.value } : x)))} />
                <div className="row" style={{ gap: 6 }}>
                  {a.format && <span className="tag olive">{a.format}</span>}
                  <button type="button" className="icon-btn" style={{ width: 34, height: 34 }} aria-label="Remove angle" onClick={() => set("angles", f.angles.filter((_, j) => j !== i))}><Trash2 size={15} strokeWidth={S} /></button>
                </div>
              </div>
              <input className="input" style={{ background: "var(--surface)", fontWeight: 600 }} value={a.hook} placeholder="Opening line"
                onChange={(e) => set("angles", f.angles.map((x, j) => (j === i ? { ...x, hook: e.target.value, source: "brand" } : x)))} />
              {a.why_now && <div className="muted small">{a.why_now}{a.trend_ref && a.trend_ref !== "evergreen" ? ` · ${a.trend_ref}` : ""}</div>}
            </div>
          ))}
          <div><button type="button" className="btn sm" onClick={() => set("angles", [...f.angles, { title: "", hook: "", format: "", why_now: "", source: "brand" }])}><Plus size={14} /> Add angle</button></div>
        </section>

        <section className="card form">
          <h2 style={{ fontSize: 18, fontWeight: 600 }}>What every post must include</h2>
          <div className="form-row">
            <Field label="Mention"><input className="input" value={f.mention} onChange={inp("mention")} placeholder="@yourbrand" /></Field>
            <Field label="Hashtags" hint="#ad (or #collab) is always required by ASCI."><input className="input" value={f.hashtags} onChange={inp("hashtags")} /></Field>
          </div>
          <div className="form-row">
            <Field label="Discount code (optional)"><input className="input" value={f.discount_code} onChange={inp("discount_code")} /></Field>
            <label className="check" style={{ alignSelf: "end", paddingBottom: 12 }}><input type="checkbox" checked={f.link_in_bio} onChange={(e) => set("link_in_bio", e.target.checked)} /> Link in bio while live</label>
          </div>
          <div className="form-row">
            <Field label="Do (one per line)"><textarea className="textarea" value={f.dos} onChange={inp("dos")} /></Field>
            <Field label="Don’t (one per line)"><textarea className="textarea" value={f.donts} onChange={inp("donts")} /></Field>
          </div>
        </section>
      </div>

      <aside className="stack-lg" style={{ position: "sticky", top: 16 }}>
        <section className="card form">
          <h2 style={{ fontSize: 18, fontWeight: 600 }}>Pay and who can apply</h2>
          <Chips onSurface value={f.pay_model} onChange={(v) => set("pay_model", v)} items={[{ id: "cpm", label: "Per view" }, { id: "hybrid", label: "Base + per view" }, { id: "flat", label: "Flat" }]} />
          <div className="form-row">
            {f.pay_model !== "flat" && <Field label="₹ per 1,000 views"><input className="input" inputMode="decimal" value={f.cpm} onChange={inp("cpm")} /></Field>}
            {f.pay_model !== "cpm" && <Field label={f.pay_model === "flat" ? "₹ per post" : "₹ base per post"}><input className="input" inputMode="decimal" value={f.flat} onChange={inp("flat")} /></Field>}
            {f.pay_model !== "flat" && <Field label="Cap per post (₹)"><input className="input" inputMode="decimal" value={f.cap} onChange={inp("cap")} /></Field>}
          </div>
          <div className="form-row">
            <Field label="Creators"><input className="input" type="number" min={1} value={f.max_creators} onChange={inp("max_creators")} /></Field>
            <Field label="Minimum tier">
              <select className="select" value={f.min_tier} onChange={inp("min_tier")}>
                {["bronze", "silver", "gold", "platinum"].map((t) => <option key={t} value={t}>{title(t)}</option>)}
              </select>
            </Field>
          </div>
          <Field label="Niches">
            <select className="select" value="" onChange={(e) => e.target.value && !f.niches.includes(e.target.value) && set("niches", [...f.niches, e.target.value].slice(0, 5))}>
              <option value="">Add a niche…</option>
              {NICHES.map((n) => <option key={n} value={n}>{title(n)}</option>)}
            </select>
            <div className="tags">{f.niches.map((n) => <button type="button" key={n} className="tag olive" style={{ border: 0, cursor: "pointer" }} onClick={() => set("niches", f.niches.filter((x) => x !== n))}>{title(n)} ×</button>)}</div>
          </Field>
          <Field label="Cities (optional, comma separated)"><input className="input" value={f.cities} onChange={inp("cities")} placeholder="Any city" /></Field>
          <div className="form-row">
            <Field label="Post by"><input className="input" type="date" value={f.deadline} onChange={inp("deadline")} /></Field>
            <Field label="Count views for (days)"><input className="input" type="number" min={7} max={90} value={f.tracking_days} onChange={inp("tracking_days")} /></Field>
          </div>
          <Field label="Usage rights">
            <select className="select" value={f.usage_rights} onChange={inp("usage_rights")}>
              <option value="organic">Organic only</option><option value="organic_paid_90d">Organic + paid ads for 90 days</option><option value="paid_perpetual">Paid ads, perpetual</option>
            </select>
          </Field>
        </section>
        <section className="card stack">
          <div className="kv">
            <div><span className="k">Max per post</span><strong className="num">{inr(money.cap)}</strong></div>
            <div><span className="k">Reserved per creator</span><strong className="num">{inr(money.per)}</strong></div>
            <div><span className="k">Needed to publish</span><strong className="num">{inr(money.total)}</strong></div>
            <div><span className="k">Wallet available</span><strong className="num" style={{ color: available >= money.total ? "var(--good)" : "var(--bad)" }}>{inr(available)}</strong></div>
          </div>
          <p className="faint small">Reserve = cap × posts + 18% GST on the {Math.round(takeRate * 100)}% platform fee. Unspent reserve returns to your wallet when tracking ends.</p>
          <ErrorNote error={error} />
          <div className="grid cols-2" style={{ gap: 8 }}>
            <button className="btn" disabled={saving} onClick={() => onSave(toPayload(f), false)}>Save draft</button>
            <button className="btn primary" disabled={saving || !f.title || !f.product} onClick={() => onSave(toPayload(f), true)}>{saving ? <Spinner /> : "Publish"}</button>
          </div>
        </section>
      </aside>
    </div>
  );
}
