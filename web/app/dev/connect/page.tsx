"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Check, FlaskConical, Instagram, Youtube } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { short, title } from "@/lib/format";
import { ErrorNote, Field, Logo, S, Spinner } from "@/components/ui";

/** Stand-in for Instagram's / Google's consent screen when PROVIDER_MODE=fake. */
function Consent() {
  const p = useSearchParams();
  const platform = p.get("platform") || "instagram";
  const [handle, setHandle] = useState("");
  const [type, setType] = useState("MEDIA_CREATOR");
  const [list, setList] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  useEffect(() => { api(`/v1/dev/fake-accounts?platform=${platform}`).then((r) => setList(r.data)).catch(() => {}); }, [platform]);
  const Icon = platform === "instagram" ? Instagram : Youtube;
  const allow = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await api("/v1/dev/oauth/authorize", { body: { platform, handle, account_type: type, state: p.get("state"), redirect_uri: p.get("redirect_uri") } });
      window.location.href = r.redirect;
    } catch (e) {
      setErr(e as ApiError);
      setBusy(false);
    }
  };
  const cancel = () => { window.location.href = `${p.get("redirect_uri")}?error=access_denied&state=${p.get("state")}`; };
  return (
    <div style={{ minHeight: "100dvh", display: "grid", placeItems: "center", padding: 16 }}>
      <div className="card stack-lg" style={{ width: "min(460px, 100%)", padding: 28 }}>
        <div className="banner-dev"><FlaskConical size={16} strokeWidth={S} /> Simulated {platform === "instagram" ? "Instagram" : "Google"} sign-in (dev mode)</div>
        <div className="row" style={{ gap: 14 }}>
          <Logo size={34} />
          <span className="faint">→</span>
          <Icon size={34} strokeWidth={S} color={platform === "instagram" ? "var(--ig)" : "var(--yt)"} />
        </div>
        <div className="stack" style={{ gap: 6 }}>
          <h1 style={{ fontSize: 22, fontWeight: 600 }}>Flu wants to read your {platform === "instagram" ? "Instagram" : "YouTube"} account</h1>
          <div className="stack small" style={{ gap: 4 }}>
            {(platform === "instagram" ? ["Profile, follower count and account type", "Your posts and their insights (views, reach, saves)"] :
              ["Your channel and uploads (read only)", "YouTube Analytics for your videos"]).map((s) => (
              <div key={s} className="row" style={{ gap: 8 }}><Check size={14} strokeWidth={2} /> {s}</div>
            ))}
          </div>
        </div>
        <Field label={platform === "instagram" ? "Instagram username" : "Channel handle"} hint="Any new handle gets a simulated history of 36 posts.">
          <input className="input" value={handle} onChange={(e) => setHandle(e.target.value)} placeholder="your.handle" autoFocus />
        </Field>
        {list.length > 0 && (
          <div className="tags">
            {list.slice(0, 8).map((a) => (
              <button key={a.handle} className="chip" style={{ height: 32, background: "var(--surface-2)" }} onClick={() => setHandle(a.handle)}>
                @{a.handle} · {short(a.followers)} · {title(a.niche)}
              </button>
            ))}
          </div>
        )}
        {platform === "instagram" && (
          <Field label="Account type">
            <select className="select" value={type} onChange={(e) => setType(e.target.value)}>
              <option value="MEDIA_CREATOR">Creator</option>
              <option value="BUSINESS">Business</option>
              <option value="PERSONAL">Personal (Flu will refuse it)</option>
            </select>
          </Field>
        )}
        <ErrorNote error={err} />
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn ghost" onClick={cancel}>Cancel</button>
          <button className="btn primary" onClick={allow} disabled={busy || !handle.trim()}>{busy ? <Spinner /> : "Allow"}</button>
        </div>
      </div>
    </div>
  );
}

export default function Page() {
  return <Suspense><Consent /></Suspense>;
}
