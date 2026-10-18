"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowRight, ChevronRight, Flame, Link2, ShieldCheck, Sparkles, Tags, Wallet } from "lucide-react";
import { api } from "@/lib/api";
import { useApi, useJob } from "@/lib/hooks";
import { date, inr, num, short } from "@/lib/format";
import { useSession } from "@/lib/session";
import { AreaChart } from "@/components/charts";
import { BriefCard, DiagnosisView } from "@/components/creator";
import { Empty, ErrorNote, Loading, Modal, Ring, S, Stat, Tier } from "@/components/ui";

export default function CreatorHome() {
  const { data, error, loading } = useApi<any>("/v1/creator/home");
  const { toast } = useSession();
  const [diagJob, setDiagJob] = useState<string | null>(null);
  const job = useJob(diagJob);
  if (loading && !data) return <Loading rows={4} />;
  if (error) return <ErrorNote error={error} />;
  const d = data;
  const c = d.checklist;
  const steps = [
    { done: c.connected, label: "Connect Instagram or YouTube", href: "/creator/accounts", icon: Link2 },
    { done: c.audit, label: c.audit_flagged ? "Account under review (usually within 48 hours)" : "Pass the account audit", href: "/creator/accounts", icon: ShieldCheck },
    { done: c.niches_confirmed, label: "Confirm your niches", href: "/creator/score#niches", icon: Tags },
    { done: c.kyc, label: "Add PAN and bank or UPI for payouts", href: "/creator/earnings#kyc", icon: Wallet },
  ];
  const pending = steps.filter((s) => !s.done);

  const diagnose = async () => {
    try {
      const r = await api(`/v1/creator/media/${d.last_post.id}/diagnose`, { method: "POST" });
      setDiagJob(r.job_id);
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  return (
    <>
      <div className="grid split">
        <section className="feature">
          {c.connected ? (
            <div className="row" style={{ gap: 20, alignItems: "center", flexWrap: "wrap" }}>
              <div style={{ background: "#f3f5ea", borderRadius: 999, padding: 6 }}><Ring value={d.score} size={92} stroke={8} /></div>
              <div className="grow" style={{ display: "grid", gap: 6, minWidth: 220 }}>
                <h2>{d.next_tier ? `${d.points_to_next_tier} points to ${d.next_tier[0].toUpperCase()}${d.next_tier.slice(1)}` : "Top tier: Platinum"}</h2>
                <p>{d.locked_count > 0 ? `${d.locked_count} brief${d.locked_count === 1 ? "" : "s"} open up as your tier rises.` : "Every brief you qualify for is open to you."}</p>
                <div><Link href="/creator/score" className="btn accent sm">See what moves your score <ArrowRight size={15} strokeWidth={2} /></Link></div>
              </div>
            </div>
          ) : (
            <div className="stack" style={{ gap: 10 }}>
              <h2>Connect an account to get your Creator Score</h2>
              <p>We read your last 30 posts, check the account and place you in a tier. It takes under a minute.</p>
              <div><Link href="/creator/accounts" className="btn accent sm">Connect now <ArrowRight size={15} strokeWidth={2} /></Link></div>
            </div>
          )}
        </section>
        <section className="card">
          <div className="card-head"><h2>{pending.length ? "Finish setting up" : "You’re all set"}</h2><span className="muted small num">{steps.length - pending.length}/{steps.length}</span></div>
          <div className="items">
            {steps.map((s) => (
              <Link key={s.label} href={s.href} className="item link-row" style={{ opacity: s.done ? 0.6 : 1 }}>
                <s.icon size={18} strokeWidth={S} />
                <span className="grow" style={{ textDecoration: s.done ? "line-through" : "none" }}>{s.label}</span>
                {!s.done && <ChevronRight size={16} strokeWidth={S} />}
              </Link>
            ))}
          </div>
        </section>
      </div>

      <div className="grid cols-4">
        <Stat k="Briefs you qualify for" v={num(d.qualifying_briefs)} d={d.locked_count ? `${d.locked_count} more at a higher tier` : "Open now"} />
        <Stat k="Earning on live posts" v={inr(d.earnings.accrued_paise)} d="Accrues as views are verified" />
        <Stat k="Paid out" v={inr(d.earnings.paid_paise)} d={d.earnings.settling_paise ? `${inr(d.earnings.settling_paise)} settling` : "To your bank or UPI"} />
        <Stat k="Posting streak" v={<span className="row" style={{ gap: 6 }}><Flame size={22} strokeWidth={S} color="var(--warn)" />{d.streak_weeks} wk</span>} d="Weeks with 3 or more posts" />
      </div>

      <section className="stack">
        <div className="card-head" style={{ margin: 0 }}><h2>Briefs for you</h2><Link href="/creator/briefs" className="link">See all <ChevronRight size={14} /></Link></div>
        {d.top_briefs.length ? (
          <div className="grid cols-3">{d.top_briefs.map((b: any) => <BriefCard key={b.id} b={b} />)}</div>
        ) : (
          <div className="card"><Empty title="No open briefs match you yet">{c.connected ? "New briefs land most weeks. Keep posting: your tier decides which ones you see." : "Connect an account first."}</Empty></div>
        )}
      </section>

      <div className="grid split">
        <section className="card">
          <div className="card-head"><h2>Score over time</h2><Tier tier={d.tier} /></div>
          {d.score_history.length > 1 ? (
            <AreaChart values={d.score_history.map((h: any) => h.score)} labels={d.score_history.map((h: any) => date(h.run_at))}
              label="Creator Score over time" fmt={(n) => String(Math.round(n))} every={Math.ceil(d.score_history.length / 6)} />
          ) : <Empty title="Your score history starts today">It updates after every completed post and once a week.</Empty>}
        </section>
        <section className="card">
          <div className="card-head"><h2>Your latest post</h2><Link href="/creator/studio" className="link">Studio <ChevronRight size={14} /></Link></div>
          {d.last_post ? (
            <div className="stack">
              <p className="ellipsis" style={{ whiteSpace: "normal" }}>{d.last_post.caption}</p>
              <div className="grid cols-3" style={{ gap: 8 }}>
                {[["Views", d.last_post.metrics?.views], ["Reach", d.last_post.metrics?.reach], ["Saves", d.last_post.metrics?.saves]].map(([k, v]) => (
                  <div key={k as string} className="card soft tight"><div className="muted small">{k}</div><div className="strong num" style={{ fontSize: 18 }}>{short(v as number)}</div></div>
                ))}
              </div>
              <button className="btn primary" onClick={diagnose}><Sparkles size={16} strokeWidth={S} /> Why did it do this?</button>
            </div>
          ) : <Empty title="No posts yet" />}
        </section>
      </div>

      {d.locked_briefs.length > 0 && (
        <section className="stack">
          <div className="card-head" style={{ margin: 0 }}><h2>Open these up next</h2></div>
          <div className="grid cols-3">{d.locked_briefs.map((b: any) => <BriefCard key={b.id} b={b} locked />)}</div>
        </section>
      )}

      <Modal open={!!diagJob} onClose={() => setDiagJob(null)} title="Post diagnosis">
        <DiagnosisView job={job} />
      </Modal>
    </>
  );
}
