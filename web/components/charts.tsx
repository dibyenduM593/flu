"use client";

import { short } from "@/lib/format";

function niceStep(v: number) {
  if (v <= 0) return 1;
  const m = Math.pow(10, Math.floor(Math.log10(v)));
  const n = v / m;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * m;
}

/** Line/area chart with flat fill (no gradients). */
export function AreaChart({ values, labels, label, fmt = short, every = 1, color = "var(--olive)" }: {
  values: number[]; labels: string[]; label: string; fmt?: (n: number) => string; every?: number; color?: string;
}) {
  const W = 640, H = 220, p = { l: 46, r: 14, t: 12, b: 28 };
  const max = Math.max(1, ...values);
  const step = niceStep(max / 4);
  const hi = step * 4;
  const n = Math.max(values.length - 1, 1);
  const x = (i: number) => p.l + (i * (W - p.l - p.r)) / n;
  const y = (v: number) => H - p.b - (v / hi) * (H - p.t - p.b);
  const pts = values.map((v, i) => [x(i), y(v)] as const);
  const d = pts.map((q, i) => `${i ? "L" : "M"}${q[0].toFixed(1)} ${q[1].toFixed(1)}`).join(" ");
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label}>
        {[0, 1, 2, 3, 4].map((k) => (
          <g key={k}>
            <line x1={p.l} x2={W - p.r} y1={y(step * k)} y2={y(step * k)} stroke="var(--surface-3)" strokeWidth="1" />
            <text x={p.l - 8} y={y(step * k) + 4} textAnchor="end" className="ax">{fmt(step * k)}</text>
          </g>
        ))}
        {labels.map((l, i) => (i % every === 0 || i === labels.length - 1) && (
          <text key={i} x={x(i)} y={H - 8} textAnchor="middle" className="ax">{l}</text>
        ))}
        {pts.length > 1 && (
          <>
            <path d={`${d} L${pts[pts.length - 1][0]} ${H - p.b} L${p.l} ${H - p.b} Z`} fill={color} fillOpacity="0.12" />
            <path d={d} fill="none" stroke={color} strokeWidth="2.25" strokeLinejoin="round" strokeLinecap="round" />
            <circle cx={pts[pts.length - 1][0]} cy={pts[pts.length - 1][1]} r="4.5" fill="var(--surface)" stroke={color} strokeWidth="2.25" />
          </>
        )}
      </svg>
    </div>
  );
}

export function Bars({ values, labels, label, fmt = short, highlightLast = true }: {
  values: number[]; labels: string[]; label: string; fmt?: (n: number) => string; highlightLast?: boolean;
}) {
  const W = 640, H = 200, p = { l: 44, r: 6, t: 10, b: 26 };
  const max = Math.max(1, ...values);
  const step = niceStep(max / 3);
  const hi = step * 3;
  const bw = (W - p.l - p.r) / Math.max(values.length, 1);
  const y = (v: number) => H - p.b - (v / hi) * (H - p.t - p.b);
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label}>
        {[0, 1, 2, 3].map((k) => (
          <g key={k}>
            <line x1={p.l} x2={W - p.r} y1={y(step * k)} y2={y(step * k)} stroke="var(--surface-3)" strokeWidth="1" />
            <text x={p.l - 8} y={y(step * k) + 4} textAnchor="end" className="ax">{fmt(step * k)}</text>
          </g>
        ))}
        {values.map((v, i) => {
          const h = Math.max(v > 0 ? 3 : 0, H - p.b - y(v));
          return (
            <g key={i}>
              <rect x={p.l + i * bw + bw * 0.18} y={H - p.b - h} width={bw * 0.64} height={h} rx={Math.min(6, bw * 0.2)}
                fill={highlightLast && i === values.length - 1 ? "var(--olive)" : "var(--olive-soft)"} />
              {(values.length <= 14 || i % 2 === 0) && (
                <text x={p.l + i * bw + bw / 2} y={H - 8} textAnchor="middle" className="ax">{labels[i]}</text>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

export function Spark({ values, color = "var(--olive)", w = 120, h = 36 }: { values: number[]; color?: string; w?: number; h?: number }) {
  if (values.length < 2) return null;
  const mn = Math.min(...values), mx = Math.max(...values);
  const pts = values.map((v, i) => [3 + (i * (w - 6)) / (values.length - 1), h - 4 - ((v - mn) / (mx - mn || 1)) * (h - 8)]);
  const d = pts.map((q, i) => `${i ? "L" : "M"}${q[0].toFixed(1)} ${q[1].toFixed(1)}`).join(" ");
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
      <path d={d} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}
