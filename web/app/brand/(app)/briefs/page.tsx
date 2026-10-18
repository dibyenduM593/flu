"use client";

import Link from "next/link";
import { Plus } from "lucide-react";
import { useApi } from "@/lib/hooks";
import { date, inr, inrShort, num, PAY_MODEL } from "@/lib/format";
import { useOrg } from "@/lib/org";
import { Empty, ErrorNote, Loading, Plat, Status, Tier } from "@/components/ui";

export default function BrandBriefs() {
  const org = useOrg();
  const { data, error, loading } = useApi<any>(org ? `/v1/orgs/${org.id}/briefs` : null);
  return (
    <>
      <div className="page-title">
        <div><h1>Briefs</h1><p>Each brief reserves every hired creator’s maximum payout in escrow, so creators know the money is there.</p></div>
        <Link href="/brand/briefs/new" className="btn primary"><Plus size={16} strokeWidth={2} /> New brief</Link>
      </div>
      <ErrorNote error={error} />
      {loading && !data ? <Loading /> : data?.data.length ? (
        <div className="grid cols-2">
          {data.data.map((b: any) => (
            <Link key={b.id} href={`/brand/briefs/${b.id}`} className="card stack fade-in">
              <div className="row between"><Status s={b.status} /><span className="muted small">{b.deadline ? `Deadline ${date(b.deadline)}` : "No deadline"}</span></div>
              <div><div className="strong" style={{ fontSize: 18 }}>{b.title}</div><div className="muted small ellipsis">{b.product}</div></div>
              <div className="tags">
                {b.platforms.map((p: string) => <span key={p} className="tag"><Plat p={p} /></span>)}
                <span className="tag">{PAY_MODEL[b.pay_model]}</span>
                <span className="tag"><Tier tier={b.min_tier} /><span style={{ fontWeight: 500 }}>and up</span></span>
              </div>
              <div className="grid cols-4" style={{ gap: 8 }}>
                {[["Hired", `${b.hired_count}/${b.max_creators}`], ["Applicants", num(b.application_count)], ["Views", num(b.performance.verified_views)],
                  ["Spent", inrShort(b.performance.cost_paise)]].map(([k, v]) => (
                  <div key={k} className="card soft tight"><div className="muted small">{k}</div><div className="strong num">{v}</div></div>
                ))}
              </div>
              {b.performance.cpm_paise && <div className="muted small">Effective CPM {inr(b.performance.cpm_paise, { decimals: true })}</div>}
            </Link>
          ))}
        </div>
      ) : <div className="card"><Empty title="No briefs yet"><Link href="/brand/briefs/new" className="link">Draft one with the Trend Brief Generator</Link></Empty></div>}
    </>
  );
}
