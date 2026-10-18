"use client";

import { useEffect } from "react";
import { AlertCircle, Inbox, Instagram, Loader2, X, Youtube } from "lucide-react";
import type { ApiError } from "@/lib/api";
import { title } from "@/lib/format";

export const S = 1.6; // icon stroke width used across the app

export function Logo({ sub, size = 28 }: { sub?: string; size?: number }) {
  return (
    <span className="logo" aria-label="Flu">
      <svg width={size} height={size} viewBox="0 0 28 28" aria-hidden="true">
        <rect width="28" height="28" rx="8" fill="var(--olive)" />
        <rect x="7.5" y="15" width="3.2" height="6" rx="1.2" fill="var(--lime)" />
        <rect x="12.4" y="11" width="3.2" height="10" rx="1.2" fill="var(--lime)" />
        <rect x="17.3" y="7" width="3.2" height="14" rx="1.2" fill="var(--lime)" />
      </svg>
      <span>flu</span>
      {sub && <small>{sub}</small>}
    </span>
  );
}

export function Ring({ value, size = 64, stroke = 7, label }: { value: number; size?: number; stroke?: number; label?: string }) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const v = Math.max(0, Math.min(100, value));
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={label || `${Math.round(v)} out of 100`}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--surface-3)" strokeWidth={stroke} />
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--olive)" strokeWidth={stroke} strokeLinecap="round"
        strokeDasharray={`${(v / 100) * c} ${c}`} transform={`rotate(-90 ${size / 2} ${size / 2})`}
        style={{ transition: "stroke-dasharray .6s cubic-bezier(.32,.72,0,1)" }} />
      <text x="50%" y="50%" dominantBaseline="central" textAnchor="middle" fill="var(--ink)"
        style={{ fontSize: size * 0.3, fontWeight: 600, letterSpacing: "-0.03em", fontVariantNumeric: "tabular-nums" }}>
        {Math.round(v)}
      </text>
    </svg>
  );
}

export function Tier({ tier }: { tier: string }) {
  return <span className={`tier ${tier}`}>{tier}</span>;
}

export function Plat({ p, children }: { p: string; children?: React.ReactNode }) {
  return (
    <span className={`plat ${p === "instagram" ? "ig" : "yt"}`}>
      {p === "instagram" ? <Instagram size={15} strokeWidth={S} /> : <Youtube size={16} strokeWidth={S} />}
      {children ?? (p === "instagram" ? "Instagram" : "YouTube")}
    </span>
  );
}

const STATUS: Record<string, [string, string]> = {
  live: ["good", "Live"], draft: ["", "Draft"], paused: ["warn", "Paused"], closed: ["", "Closed"],
  applied: ["", "Applied"], shortlisted: ["olive", "Shortlisted"], accepted: ["good", "Hired"], rejected: ["bad", "Not selected"],
  withdrawn: ["", "Withdrawn"], submitted: ["warn", "Awaiting approval"], approved: ["good", "Approved"],
  auto_approved: ["good", "Auto-approved"], disputed: ["bad", "Disputed"], active: ["good", "Active"],
  completed: ["", "Completed"], cancelled: ["", "Cancelled"], queued: ["warn", "On hold"], processing: ["olive", "Settling"],
  processed: ["good", "Paid"], reversed: ["bad", "Reversed"], failed: ["bad", "Failed"], verified: ["good", "Verified"],
  pending: ["warn", "Pending"], none: ["", "Not started"], open: ["warn", "Open"], resolved: ["", "Resolved"],
  pass: ["good", "Passed"], flag: ["warn", "Under review"], fail: ["bad", "Failed"], needs_reauth: ["bad", "Reconnect"],
  revoked: ["", "Disconnected"], tracking: ["olive", "Tracking"], frozen: ["bad", "Frozen"], ended: ["", "Window closed"],
  held: ["warn", "Held"], cleared: ["good", "Cleared"], captured: ["good", "Captured"], created: ["", "Created"],
};

export function Status({ s, children }: { s: string; children?: React.ReactNode }) {
  const [cls, label] = STATUS[s] || ["", title(s)];
  return <span className={`tag ${cls}`}>{children ?? label}</span>;
}

export function Empty({ title: t, children, icon }: { title: string; children?: React.ReactNode; icon?: React.ReactNode }) {
  return (
    <div className="empty">
      {icon ?? <Inbox size={28} strokeWidth={S} />}
      <h3>{t}</h3>
      {children && <div className="small">{children}</div>}
    </div>
  );
}

export function Loading({ rows = 3 }: { rows?: number }) {
  return (
    <div className="stack" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skeleton" style={{ height: i === 0 ? 120 : 64 }} />
      ))}
    </div>
  );
}

export function Spinner({ size = 16 }: { size?: number }) {
  return <Loader2 size={size} strokeWidth={2} style={{ animation: "spin 0.9s linear infinite" }} aria-hidden="true" />;
}

export function ErrorNote({ error }: { error: ApiError | Error | null | undefined }) {
  if (!error) return null;
  const details = (error as ApiError).details as any;
  return (
    <div className="note bad" role="alert">
      <AlertCircle size={16} strokeWidth={S} />
      <div>
        {error.message}
        {details?.reasons && <div>{(details.reasons as string[]).join(" · ")}</div>}
        {details?.issues && <div>{(details.issues as string[]).join(" · ")}</div>}
      </div>
    </div>
  );
}

export function Modal({ open, onClose, title: t, children, wide }: {
  open: boolean; onClose: () => void; title: string; children: React.ReactNode; wide?: boolean;
}) {
  useEffect(() => {
    if (!open) return;
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${wide ? "wide" : ""}`} role="dialog" aria-modal="true" aria-label={t}>
        <div className="row between">
          <h2>{t}</h2>
          <button className="icon-btn" style={{ background: "var(--surface-2)" }} onClick={onClose} aria-label="Close">
            <X size={18} strokeWidth={S} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Tabs<T extends string>({ value, onChange, items }: {
  value: T; onChange: (v: T) => void; items: { id: T; label: string; count?: number }[];
}) {
  return (
    <div className="tabs" role="tablist">
      {items.map((i) => (
        <button key={i.id} role="tab" aria-selected={value === i.id} onClick={() => onChange(i.id)}>
          {i.label}
          {i.count != null && <span className="num" style={{ opacity: 0.7, marginLeft: 6 }}>{i.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Chips<T extends string>({ value, onChange, items, onSurface }: {
  value: T; onChange: (v: T) => void; items: { id: T; label: string }[]; onSurface?: boolean;
}) {
  return (
    <div className={`chips ${onSurface ? "on-surface" : ""}`}>
      {items.map((i) => (
        <button key={i.id} className="chip" aria-pressed={value === i.id} onClick={() => onChange(i.id)}>
          {i.label}
        </button>
      ))}
    </div>
  );
}

export function Stat({ k, v, d }: { k: string; v: React.ReactNode; d?: React.ReactNode }) {
  return (
    <div className="stat">
      <span className="k">{k}</span>
      <span className="v">{v}</span>
      {d && <span className="d">{d}</span>}
    </div>
  );
}

export function Meter({ value, lime }: { value: number; lime?: boolean }) {
  return (
    <div className={`meter ${lime ? "lime" : ""}`} role="meter" aria-valuenow={Math.round(value * 100)} aria-valuemin={0} aria-valuemax={100}>
      <i style={{ ["--w" as any]: `${Math.max(0, Math.min(1, value)) * 100}%` }} />
    </div>
  );
}

export function Field({ label, hint, children, htmlFor }: { label: string; hint?: React.ReactNode; children: React.ReactNode; htmlFor?: string }) {
  return (
    <div className="field">
      <label htmlFor={htmlFor}>{label}</label>
      {children}
      {hint && <span className="hint">{hint}</span>}
    </div>
  );
}
