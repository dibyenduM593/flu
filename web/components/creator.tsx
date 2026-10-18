"use client";

import Link from "next/link";
import { useState } from "react";
import { CalendarDays, Copy, Lock, ThumbsDown, ThumbsUp } from "lucide-react";
import { api } from "@/lib/api";
import { date, inr, initials, PAY_MODEL, payLine, title } from "@/lib/format";
import { Plat, S, Spinner, Tier } from "./ui";

export function BriefCard({ b, locked }: { b: any; locked?: boolean }) {
  return (
    <Link href={`/creator/briefs/${b.id}`} className="card fade-in" style={{ display: "grid", gap: 12, opacity: locked ? 0.86 : 1 }}>
      <div className="row">
        <div className="avatar square">{initials(b.org.name)}</div>
        <div className="grow">
          <div className="muted small ellipsis">{b.org.name}</div>
          <div className="strong ellipsis" style={{ fontSize: 16 }}>{b.title}</div>
        </div>
        {b.application_status && <span className="tag olive">{title(b.application_status === "accepted" ? "hired" : b.application_status)}</span>}
      </div>
      <div className="tags">
        {b.platforms.map((p: string) => <span key={p} className="tag"><Plat p={p} /></span>)}
        <span className="tag">{PAY_MODEL[b.pay_model]}</span>
        <span className="tag"><Tier tier={b.min_tier} /><span style={{ fontWeight: 500 }}>and up</span></span>
      </div>
      <div className="row between" style={{ alignItems: "flex-end" }}>
        <div>
          <div className="muted small">You could earn</div>
          <div style={{ fontSize: 24, fontWeight: 600, letterSpacing: "-0.03em" }} className="num">{inr(b.expected.total_paise)}</div>
          <div className="faint small">{payLine(b)}</div>
        </div>
        <div className="muted small row" style={{ gap: 6 }}>
          <CalendarDays size={14} strokeWidth={S} /> {b.deadline ? `Post by ${date(b.deadline)}` : "Open"}
        </div>
      </div>
      {locked && b.locked_reasons && (
        <div className="note" style={{ padding: "10px 12px" }}>
          <Lock size={15} strokeWidth={S} />
          <span>{b.locked_reasons.join(" · ")}</span>
        </div>
      )}
    </Link>
  );
}

export function Feedback({ jobId, initial }: { jobId: string; initial?: string | null }) {
  const [v, setV] = useState<string | null>(initial ?? null);
  const send = async (f: "up" | "down") => {
    setV(f);
    await api(`/v1/jobs/${jobId}/feedback`, { body: { feedback: f } }).catch(() => {});
  };
  return (
    <div className="row" style={{ gap: 6 }}>
      <span className="muted small">Useful?</span>
      <button className={`icon-btn ${v === "up" ? "olive" : ""}`} style={{ width: 34, height: 34, background: v === "up" ? undefined : "var(--surface-2)" }} onClick={() => send("up")} aria-label="Useful"><ThumbsUp size={15} strokeWidth={S} /></button>
      <button className={`icon-btn ${v === "down" ? "olive" : ""}`} style={{ width: 34, height: 34, background: v === "down" ? undefined : "var(--surface-2)" }} onClick={() => send("down")} aria-label="Not useful"><ThumbsDown size={15} strokeWidth={S} /></button>
    </div>
  );
}

const ISSUE: Record<string, string> = {
  hook: "The opening", length: "The length", timing: "The posting time", topic: "The topic", cta: "The ending", none: "Nothing major",
};

export function DiagnosisView({ job }: { job: any }) {
  if (!job || job.status === "queued" || job.status === "running")
    return <div className="row muted"><Spinner /> Reading your post’s numbers…</div>;
  if (job.status === "failed") return <div className="note bad">Diagnosis failed: {job.error}</div>;
  const o = job.output;
  return (
    <div className="stack-lg">
      <div className="card soft" style={{ display: "grid", gap: 6 }}>
        <span className="muted small">Main issue</span>
        <div style={{ fontSize: 22, fontWeight: 600, letterSpacing: "-0.02em" }}>{ISSUE[o.primary_issue] || o.primary_issue}</div>
        <p>{o.summary}</p>
      </div>
      {o.evidence?.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Metric</th><th className="r">This post</th><th className="r">Compared with</th></tr></thead>
            <tbody>
              {o.evidence.map((e: any, i: number) => (
                <tr key={i}><td>{e.metric}</td><td className="r num strong">{e.value}</td><td className="r muted">{e.benchmark}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="stack">
        <h3 style={{ fontSize: 16, fontWeight: 600 }}>Three fixes for your next post</h3>
        {o.fixes.map((f: any, i: number) => (
          <div key={i} className="angle">
            <div className="hook">{f.what}</div>
            <div className="muted">{f.why}</div>
            <div className="small"><span className="muted">Try: </span>{f.example}</div>
          </div>
        ))}
      </div>
      {o.note && <div className="note">{o.note}</div>}
      <div className="row between wrap-row">
        <span className="faint small">{job.model === "flu-heuristic-v1" ? "Flu rules engine" : job.model} · {job.prompt_version}</span>
        <Feedback jobId={job.id} initial={job.feedback} />
      </div>
    </div>
  );
}

export function HookCard({ h, onCopy }: { h: any; onCopy?: () => void }) {
  return (
    <div className="angle">
      <div className="row between">
        <span className="tag olive">{h.pattern}</span>
        {h.used_media_id && <span className="tag good">Used</span>}
      </div>
      <div className="hook">“{h.first_line}”</div>
      <div className="small"><span className="muted">On screen: </span><strong>{h.on_screen_text}</strong></div>
      <div className="muted small">{h.why_it_fits}</div>
      <div>
        <button className="btn sm on-surface" style={{ background: "var(--surface)" }} onClick={() => { navigator.clipboard?.writeText(h.first_line); onCopy?.(); }}>
          <Copy size={14} strokeWidth={S} /> Copy line
        </button>
      </div>
    </div>
  );
}
