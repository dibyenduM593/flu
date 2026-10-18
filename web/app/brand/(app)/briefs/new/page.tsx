"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Sparkles } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useApi, useJob } from "@/lib/hooks";
import { inr, NICHES, title } from "@/lib/format";
import { useOrg } from "@/lib/org";
import { useSession } from "@/lib/session";
import { BriefEditor, BriefForm, fromBrief } from "@/components/BriefEditor";
import { Chips, ErrorNote, Field, S, Spinner } from "@/components/ui";

function draftToForm(out: any, inp: any): BriefForm {
  const mix = out.creator_mix || {};
  const minTier = ["bronze", "silver", "gold", "platinum"].find((t) => (mix[t] || 0) > 0) || "bronze";
  const cpm = Math.round(((out.suggested_cpm_paise?.low || 4000) + (out.suggested_cpm_paise?.high || 8000)) / 2);
  const payModel = inp.goal === "awareness" ? "cpm" : "hybrid";
  return fromBrief({
    title: out.title, product: inp.product, goal: inp.goal, platforms: inp.platforms, pay_model: payModel, cpm_paise: cpm,
    cap_paise: out.suggested_cap_paise, flat_paise: payModel === "hybrid" ? Math.round(out.suggested_cap_paise * 0.25 / 100) * 100 : 0,
    min_tier: minTier, niches: inp.niches, max_creators: out.creator_count, required_elements: out.required_elements,
    dos: out.dos, donts: out.donts, angles: out.angles.map((a: any) => ({ ...a, source: "ai" })),
    deliverable_type: inp.platforms[0] === "youtube" ? "short" : "reel",
  });
}

export default function NewBrief() {
  const org = useOrg();
  const router = useRouter();
  const { toast } = useSession();
  const wallet = useApi<any>(org ? `/v1/orgs/${org.id}/wallet` : null);
  const orgInfo = useApi<any>(org ? `/v1/orgs/${org.id}` : null);
  const [inp, setInp] = useState({ product_name: "", product: "", goal: "awareness", budget: "100000", platforms: ["instagram"], niches: [] as string[], tone: "" });
  const [jobId, setJobId] = useState<string | null>(null);
  const job = useJob(jobId);
  const [form, setForm] = useState<BriefForm | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);

  useEffect(() => {
    if (job?.status === "done" && !form) {
      const f = draftToForm(job.output, job.output && { ...inp, niches: inp.niches });
      f.ai_draft_id = job.id;
      setForm(f);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job]);

  const generate = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    setForm(null);
    try {
      const r = await api(`/v1/orgs/${org!.id}/briefs/draft`, { body: {
        product: inp.product, product_name: inp.product_name || null, goal: inp.goal, budget_paise: Math.round(Number(inp.budget) * 100),
        platforms: inp.platforms, niches: inp.niches, tone: inp.tone || null,
      } });
      setJobId(r.job_id);
    } catch (e) {
      setErr(e as ApiError);
    }
  };

  const save = async (payload: any, publish: boolean) => {
    setBusy(true);
    setErr(null);
    try {
      const b = await api(`/v1/orgs/${org!.id}/briefs`, { body: payload });
      if (publish) {
        try {
          await api(`/v1/briefs/${b.id}/publish`, { method: "POST" });
          toast("Published. Matching creators are being notified.");
        } catch (e) {
          toast("Saved as a draft; it couldn’t be published yet.", "error");
          router.push(`/brand/briefs/${b.id}?tab=brief`);
          return;
        }
      } else toast("Draft saved");
      router.push(`/brand/briefs/${b.id}`);
    } catch (e) {
      setErr(e as ApiError);
    } finally {
      setBusy(false);
    }
  };

  const generating = jobId && job?.status !== "done" && job?.status !== "failed";
  return (
    <>
      <div className="page-title"><div><h1>New brief</h1><p>Tell us the product and the goal. You get five trend-grounded angles, a CPM band and a creator mix to edit before you publish.</p></div></div>
      {!form && (
        <form className="card form" onSubmit={generate} style={{ maxWidth: 820 }}>
          <div className="form-row">
            <Field label="Product name"><input className="input" value={inp.product_name} onChange={(e) => setInp({ ...inp, product_name: e.target.value })} placeholder="Saffron lip balm" /></Field>
            <Field label="Budget for this brief (₹)"><input className="input" inputMode="numeric" value={inp.budget} onChange={(e) => setInp({ ...inp, budget: e.target.value.replace(/\D/g, "") })} /></Field>
          </div>
          <Field label="Describe it in a sentence" hint="Price and where it ships help us suggest a realistic goal and creator mix.">
            <textarea className="textarea" value={inp.product} onChange={(e) => setInp({ ...inp, product: e.target.value })} placeholder="Ayurvedic saffron lip balm, ₹299, ships pan-India, for dry winter lips" />
          </Field>
          <Field label="Goal">
            <Chips onSurface value={inp.goal} onChange={(g) => setInp({ ...inp, goal: g })} items={[{ id: "awareness", label: "Awareness" }, { id: "orders", label: "Orders" }, { id: "installs", label: "App installs" }]} />
          </Field>
          <div className="form-row">
            <Field label="Platform">
              <Chips onSurface value={inp.platforms[0]} onChange={(p) => setInp({ ...inp, platforms: [p] })} items={[{ id: "instagram", label: "Instagram Reels" }, { id: "youtube", label: "YouTube Shorts" }]} />
            </Field>
            <Field label="Niches">
              <select className="select" value="" onChange={(e) => e.target.value && !inp.niches.includes(e.target.value) && setInp({ ...inp, niches: [...inp.niches, e.target.value].slice(0, 3) })}>
                <option value="">Add a niche…</option>
                {NICHES.map((n) => <option key={n} value={n}>{title(n)}</option>)}
              </select>
              <div className="tags">{inp.niches.map((n) => <button type="button" key={n} className="tag olive" style={{ border: 0, cursor: "pointer" }} onClick={() => setInp({ ...inp, niches: inp.niches.filter((x) => x !== n) })}>{title(n)} ×</button>)}</div>
            </Field>
          </div>
          <ErrorNote error={err} />
          {job?.status === "failed" && <div className="note bad">The draft failed: {job.error}</div>}
          <div className="row wrap-row">
            <button className="btn primary" disabled={!!generating || inp.product.trim().length < 5 || Number(inp.budget) < 10000}>
              {generating ? <><Spinner /> Reading this week’s trends…</> : <><Sparkles size={16} strokeWidth={S} /> Draft my brief</>}
            </button>
            <button type="button" className="btn ghost" onClick={() => setForm(fromBrief({ product: inp.product, title: inp.product_name, niches: inp.niches, platforms: inp.platforms, goal: inp.goal, cpm_paise: 5000, cap_paise: 500000 }))}>Start from scratch</button>
            <span className="muted small">Budget {inr(Number(inp.budget) * 100)}</span>
          </div>
        </form>
      )}
      {form && (
        <>
          {job?.output && (
            <div className="note good">
              <Sparkles size={16} strokeWidth={S} />
              <span>Drafted with {job.model === "flu-heuristic-v1" ? "Flu’s rules engine (no AI key configured)" : job.model}. CPM band {inr(job.output.suggested_cpm_paise.low, { decimals: true })} to {inr(job.output.suggested_cpm_paise.high, { decimals: true })} from {job.output.pricing_source === "fallback_table" ? "Flu’s starting price table" : "what Flu brands paid in your niche"}; {job.output.creator_count} creators suggested.</span>
            </div>
          )}
          <BriefEditor initial={form} takeRate={orgInfo.data?.take_rate ?? 0.15} available={wallet.data?.summary.available_paise ?? 0} onSave={save} saving={busy} error={err} />
        </>
      )}
    </>
  );
}
