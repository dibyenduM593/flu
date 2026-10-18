"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Instagram, Youtube } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { datetime, num, pct, short } from "@/lib/format";
import { useSession } from "@/lib/session";
import { ErrorNote, Loading, S, Spinner, Status } from "@/components/ui";

const ERR: Record<string, string> = {
  personal_account: "That’s a personal Instagram account. Switch to a Creator account in Instagram settings (two taps, free), then connect again.",
  account_taken: "That account is already connected to another Flu creator.",
  invalid_state: "The connection link expired. Start again.",
  cancelled: "Connection cancelled.",
  insights_not_granted: "Flu needs permission to read your post insights. Connect again and leave that permission on.",
  instagram_not_configured: "Instagram isn’t set up on this server yet (missing app ID and secret).",
};

const FLAG: Record<string, string> = {
  views_without_engagement: "Views far above followers with very little engagement",
  follower_spike: "Follower count jumped more than 30% in a month",
  duplicate_comments: "Many comments are identical",
};

function Accounts() {
  const { data, error, loading, reload } = useApi<any>("/v1/creator/audit");
  const params = useSearchParams();
  const router = useRouter();
  const { toast, refreshMe } = useSession();
  const [busy, setBusy] = useState<string | null>(null);

  const handleResult = (r: { connected?: string | null; handle?: string | null; error?: string | null; message?: string | null }) => {
    setBusy(null);
    if (r.connected) {
      toast(`Connected @${r.handle}. Reading your last 30 posts…`);
      const t = setInterval(reload, 1500);
      setTimeout(() => { clearInterval(t); reload(); refreshMe(); }, 15000);
    } else if (r.error) {
      toast(ERR[r.error] || r.message || r.error, "error");
    }
  };

  useEffect(() => {
    // Full-page fallback (popup blocked): /connect/done redirects here with the result in the query string.
    const c = params.get("connected"), e = params.get("error");
    if (c || e) {
      handleResult({ connected: c, handle: params.get("handle"), error: e, message: params.get("message") });
      router.replace("/creator/accounts");
    }
    const onMessage = (ev: MessageEvent) => {
      if (ev.origin === window.location.origin && ev.data?.type === "flu:connect") handleResult(ev.data);
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const connect = async (platform: string) => {
    setBusy(platform);
    // Open the window inside the click so popup blockers allow it, then point it at the consent screen.
    const w = window.open("", "flu-connect", "popup,width=520,height=760");
    try {
      const r = await api(`/v1/connections/${platform}/start`, { method: "POST" });
      if (w) {
        w.location.href = r.url;
        const closed = setInterval(() => { if (w.closed) { clearInterval(closed); setBusy(null); } }, 700);
      } else {
        window.location.href = r.url;
      }
    } catch (e: any) {
      w?.close();
      toast(e.message, "error");
      setBusy(null);
    }
  };
  const disconnect = async (id: string) => {
    if (!confirm("Disconnect this account? Tracking stops for posts on it.")) return;
    await api(`/v1/connections/${id}`, { method: "DELETE" });
    reload();
  };

  if (loading && !data) return <Loading />;
  if (error) return <ErrorNote error={error} />;
  const byPlatform = Object.fromEntries((data.data as any[]).filter((x) => x.account.status !== "revoked").map((x) => [x.account.platform, x]));
  return (
    <>
      <div className="page-title"><div><h1>Connected accounts</h1><p>Flu reads your posts and their numbers. It never posts for you. Personal Instagram accounts can’t be read, so connect a Creator or Business account.</p></div></div>
      <div className="grid cols-2">
        {(["instagram", "youtube"] as const).map((p) => {
          const x = byPlatform[p];
          const Icon = p === "instagram" ? Instagram : Youtube;
          const m = x?.audit?.metrics;
          return (
            <section key={p} className="card stack-lg">
              <div className="row between">
                <div className="row"><Icon size={24} strokeWidth={S} color={p === "instagram" ? "var(--ig)" : "var(--yt)"} />
                  <div><div className="strong">{p === "instagram" ? "Instagram" : "YouTube Shorts"}</div><div className="muted small">{x ? `@${x.account.handle}` : p === "instagram" ? "Instagram Login" : "Google sign-in"}</div></div>
                </div>
                {x ? <Status s={x.account.status === "active" ? (x.audit?.result || "pending") : x.account.status} /> : <span className="tag">Not connected</span>}
              </div>
              {x?.audit && m ? (
                <>
                  <div className="grid cols-3" style={{ gap: 8 }}>
                    {[["Followers", short(m.followers)], ["Median views", short(m.median_views)], ["Engagement", pct(m.engagement_rate)],
                      ["Reach / followers", `${m.reach_ratio}×`], ["Posts a week", m.posts_per_week], ["30-day growth", m.follower_growth_30d != null ? pct(m.follower_growth_30d) : "—"]].map(([k, v]) => (
                      <div key={k as string} className="card soft tight"><div className="muted small">{k}</div><div className="strong num">{v}</div></div>
                    ))}
                  </div>
                  {x.audit.fraud_flags.length > 0 && (
                    <div className="note warn" style={{ display: "grid" }}>
                      <strong>Our team is reviewing this account</strong>
                      {x.audit.fraud_flags.map((f: string) => <span key={f}>{FLAG[f] || f}</span>)}
                      <span>You can still use Studio. Briefs open once the review clears, usually within 48 hours.</span>
                    </div>
                  )}
                  <div className="row between wrap-row">
                    <span className="faint small">Audited {datetime(x.audit.run_at)} · {num(m.posts_analysed)} posts</span>
                    <button className="btn sm ghost" onClick={() => disconnect(x.account.id)}>Disconnect</button>
                  </div>
                </>
              ) : x ? (
                <div className="row muted"><Spinner /> Reading your last 30 posts…</div>
              ) : (
                <>
                  <p className="muted">{p === "instagram" ? "Reads your Reels, their views, reach and saves, and when your followers are online." : "Reads your Shorts and their views. Each platform is matched separately."}</p>
                  <div><button className="btn primary" onClick={() => connect(p)} disabled={busy === p}>{busy === p ? <Spinner /> : `Connect ${p === "instagram" ? "Instagram" : "YouTube"}`}</button></div>
                </>
              )}
              {x?.account.status === "needs_reauth" && <button className="btn primary" onClick={() => connect(p)}>Reconnect</button>}
            </section>
          );
        })}
      </div>
    </>
  );
}

export default function Page() {
  return <Suspense><Accounts /></Suspense>;
}
