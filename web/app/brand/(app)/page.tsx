"use client";

import Link from "next/link";
import { ArrowRight, ChevronRight, Plus } from "lucide-react";
import { useApi } from "@/lib/hooks";
import { cpm, date, inr, inrShort, num, rel, short } from "@/lib/format";
import { useOrg } from "@/lib/org";
import { Bars } from "@/components/charts";
import { Empty, ErrorNote, Loading, Plat, Stat, Status } from "@/components/ui";

export default function BrandHome() {
  const org = useOrg();
  const { data, error, loading } = useApi<any>(org ? `/v1/orgs/${org.id}/overview` : null);
  const briefs = useApi<any>(org ? `/v1/orgs/${org.id}/briefs` : null);
  if (loading && !data) return <Loading rows={4} />;
  if (error) return <ErrorNote error={error} />;
  const k = data.kpis;
  const w = data.wallet;
  return (
    <>
      <div className="grid split">
        <section className="feature">
          <h2>Get 30 Reels live this month without an agency</h2>
          <p>Describe the product and the goal. Flu drafts five trend-grounded angles, a CPM band and a creator mix, then pays only for verified views.</p>
          <div className="row wrap-row">
            <Link href="/brand/briefs/new" className="btn accent"><Plus size={16} strokeWidth={2} /> New brief</Link>
            <Link href="/brand/creators" className="btn" style={{ background: "rgba(255,255,255,0.12)", color: "#f3f5ea" }}>Browse creators</Link>
          </div>
        </section>
        <section className="card stack">
          <div className="card-head" style={{ margin: 0 }}><h2>Wallet</h2><Link href="/brand/wallet" className="link">Top up <ChevronRight size={14} /></Link></div>
          <div className="big-number">{inr(w.available_paise)}</div>
          <div className="muted small">Available to fund new hires</div>
          <div className="kv small">
            <div><span className="k">Held in escrow for hires</span><span className="num">{inr(w.reserved_paise)}</span></div>
            <div><span className="k">Paid to creators</span><span className="num">{inr(w.paid_to_creators_paise)}</span></div>
            <div><span className="k">Platform fee + GST</span><span className="num">{inr(w.fees_paise + w.fee_gst_paise)}</span></div>
          </div>
        </section>
      </div>

      <div className="grid cols-4">
        <Stat k="Verified views bought" v={short(k.verified_views)} d="After the anomaly filter" />
        <Stat k="Effective CPM" v={k.cpm_paise ? inr(k.cpm_paise, { decimals: true }) : "—"} d="Cost per 1,000 verified views" />
        <Stat k="Spent on views" v={inrShort(k.cost_paise)} d={`${k.live_briefs} live brief${k.live_briefs === 1 ? "" : "s"}`} />
        <Stat k="Waiting on you" v={num(k.pending_approvals + k.new_applications)} d={`${k.pending_approvals} approvals · ${k.new_applications} applicants`} />
      </div>

      <div className="grid split">
        <section className="card">
          <div className="card-head"><h2>Verified views, last 14 days</h2></div>
          <Bars values={data.daily.map((d: any) => d.views)} labels={data.daily.map((d: any) => date(d.date).split(" ")[0])} label="Verified views per day" />
        </section>
        <section className="card">
          <div className="card-head"><h2>Approve within 72 hours</h2></div>
          {data.pending_approvals.length ? (
            <div className="items">
              {data.pending_approvals.map((p: any) => (
                <Link key={p.deliverable_id} href={`/brand/briefs/${p.brief_id}?tab=posts`} className="item link-row">
                  <div className="grow"><div className="strong">{p.creator}</div><div className="muted small ellipsis">{p.brief_title}</div></div>
                  <span className="tag warn">Auto-approves {rel(p.deadline)}</span>
                </Link>
              ))}
            </div>
          ) : <Empty title="No posts waiting">New submissions show up here with a countdown.</Empty>}
        </section>
      </div>

      <section className="card">
        <div className="card-head"><h2>Briefs</h2><Link href="/brand/briefs" className="link">All briefs <ChevronRight size={14} /></Link></div>
        {briefs.data?.data.length ? (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Brief</th><th>Platform</th><th className="r">Creators</th><th className="r">Applicants</th><th className="r">Verified views</th><th className="r">CPM</th><th>Status</th></tr></thead>
              <tbody>
                {briefs.data.data.slice(0, 6).map((b: any) => (
                  <tr key={b.id}>
                    <td><Link href={`/brand/briefs/${b.id}`} className="strong">{b.title}</Link><span className="sub">{b.deadline ? `Deadline ${date(b.deadline)}` : "No deadline"}</span></td>
                    <td>{b.platforms.map((p: string) => <Plat key={p} p={p} />)}</td>
                    <td className="r num">{b.hired_count}/{b.max_creators}</td>
                    <td className="r num">{b.application_count}</td>
                    <td className="r num">{num(b.performance.verified_views)}</td>
                    <td className="r num">{b.performance.cpm_paise ? inr(b.performance.cpm_paise, { decimals: true }) : "—"}</td>
                    <td><Status s={b.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <Empty title="No briefs yet"><Link href="/brand/briefs/new" className="link">Draft your first brief <ArrowRight size={13} /></Link></Empty>}
      </section>
    </>
  );
}
