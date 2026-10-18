"use client";

import { useEffect, useState } from "react";
import { TrendingUp } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { NICHES, pct, title } from "@/lib/format";
import { useSession } from "@/lib/session";
import { ErrorNote, Loading, Meter, Ring, S, Spinner, Tier } from "@/components/ui";

const FMT: Record<string, (v: number) => string> = {
  eng: (v) => pct(v), reach: (v) => `${v.toFixed(2)}× followers`, cons: (v) => `${Math.round(v * 8)} of 8 weeks`,
  growth: (v) => `${v >= 0 ? "+" : ""}${pct(v)}`, hook: (v) => pct(v, 0),
};

const BANDS = [["bronze", "Under 40"], ["silver", "40 to 59"], ["gold", "60 to 79"], ["platinum", "80 and up"]];

function Niches() {
  const { data, reload } = useApi<any>("/v1/creator/home");
  const { toast, refreshMe } = useSession();
  const [sel, setSel] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (data) setSel(data.niches || []); }, [data]);
  if (!data) return null;
  const toggle = (n: string) => setSel(sel.includes(n) ? sel.filter((x) => x !== n) : sel.length < 3 ? [...sel, n] : sel);
  const save = async () => {
    setBusy(true);
    try {
      await api("/v1/creator/niches", { method: "PATCH", body: { niches: sel } });
      toast("Niches saved");
      reload();
      refreshMe();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="card stack" id="niches">
      <div className="card-head" style={{ margin: 0 }}>
        <h2>Your niches</h2>
        {data.checklist.niches_confirmed ? <span className="tag good">Confirmed</span> : <span className="tag warn">Suggested from your captions</span>}
      </div>
      <p className="muted small">Pick up to three. Your first niche is the group your score is compared within, and briefs match on all three.</p>
      <div className="tags">
        {NICHES.map((n) => {
          const on = sel.includes(n);
          const conf = data.niche_confidence?.[n];
          return (
            <button key={n} className="chip" aria-pressed={on} onClick={() => toggle(n)} style={{ height: 34, background: on ? undefined : "var(--surface-2)" }}>
              {sel.indexOf(n) === 0 ? "Main: " : ""}{title(n)}{conf && !on ? ` · ${Math.round(conf * 100)}%` : ""}
            </button>
          );
        })}
      </div>
      <div><button className="btn primary" onClick={save} disabled={busy || !sel.length}>{busy ? <Spinner /> : "Save niches"}</button></div>
    </section>
  );
}

export default function Score() {
  const { data, error, loading } = useApi<any>("/v1/creator/score");
  if (loading && !data) return <Loading />;
  if (error) return <><ErrorNote error={error} /><Niches /></>;
  const d = data;
  const lever = d.fastest_lever;
  return (
    <>
      <div className="page-title"><div><h1>Creator Score</h1><p>A 0 to 100 grade from your last 30 posts, compared with {d.cohort.size} creators{d.cohort.niche ? ` in ${title(d.cohort.niche)}` : ""}. It decides your tier, and your tier decides which briefs you see.</p></div></div>
      <div className="grid split">
        <section className="card row" style={{ gap: 28, flexWrap: "wrap", alignItems: "center" }}>
          <Ring value={d.stored_score} size={148} stroke={11} label={`Creator Score ${d.stored_score}`} />
          <div className="stack grow" style={{ minWidth: 240 }}>
            <Tier tier={d.stored_tier} />
            <div style={{ fontSize: 22, fontWeight: 600, letterSpacing: "-0.02em" }}>
              {d.next_tier ? `${d.points_to_next_tier} points to ${title(d.next_tier)}` : "You’re in the top tier"}
            </div>
            <div className="row wrap-row" style={{ gap: 6 }}>
              {BANDS.map(([t, r]) => (
                <span key={t} className="tag" style={{ background: t === d.stored_tier ? "var(--olive-soft)" : undefined }}><Tier tier={t} /><span style={{ fontWeight: 500 }}>{r}</span></span>
              ))}
            </div>
          </div>
        </section>
        <section className="feature">
          <div className="row" style={{ gap: 10 }}><TrendingUp size={20} strokeWidth={S} color="var(--lime)" /><span style={{ color: "#d6dcc6" }}>Fastest way up</span></div>
          <h2>{lever.label}</h2>
          <p>{lever.tip}</p>
          <p style={{ color: "#f3f5ea" }}>Moving up a quarter of your group here adds about <strong>{lever.gain_if_top_quartile_step} points</strong>.</p>
        </section>
      </div>

      <section className="card">
        <div className="card-head"><h2>What your score is made of</h2><span className="muted small">{d.model_version}</span></div>
        <div className="stack-lg">
          {Object.entries(d.breakdown).map(([k, v]: any) => (
            <div key={k} className="grid" style={{ gridTemplateColumns: "minmax(0, 1.1fr) minmax(0, 1.4fr) 90px", gap: 16, alignItems: "center" }}>
              <div>
                <div className="strong">{v.label} <span className="faint small">· weight {Math.round(v.weight * 100)}%</span></div>
                <div className="muted small">{v.definition}</div>
              </div>
              <div className="stack" style={{ gap: 6 }}>
                <Meter value={v.percentile} />
                <div className="row between small"><span className="muted">You: {FMT[k](v.value)}</span><span className="muted num">Ahead of {Math.round(v.percentile * 100)}%</span></div>
              </div>
              <div className="num strong" style={{ textAlign: "right", fontSize: 18 }}>{v.points.toFixed(1)}<span className="faint small"> pts</span></div>
            </div>
          ))}
        </div>
      </section>
      <Niches />
    </>
  );
}
