"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowRight, Building2, Camera, Check, KeyRound } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { homeFor, useSession } from "@/lib/session";
import { ErrorNote, Logo, S, Spinner } from "@/components/ui";

const DEMO = [
  { phone: "9000000001", who: "Riya Kulkarni", what: "Creator, Pune. New, not yet hired" },
  { phone: "9000000002", who: "Arjun at Kesari Naturals", what: "Brand, skincare" },
  { phone: "9000000004", who: "Meera at Loop Bottles", what: "Brand, home and kitchen" },
  { phone: "9000000003", who: "Flu ops", what: "Trust queue and simulator" },
];

function Login() {
  const { me, ready, signIn } = useSession();
  const router = useRouter();
  const params = useSearchParams();
  const [step, setStep] = useState<"phone" | "otp">("phone");
  const [phone, setPhone] = useState("");
  const [otp, setOtp] = useState("");
  const [devOtp, setDevOtp] = useState<string | null>(null);
  const [isNew, setIsNew] = useState(false);
  const [role, setRole] = useState<"creator" | "brand_member">("creator");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    if (ready && me) router.replace(params.get("next") || homeFor(me));
  }, [ready, me, router, params]);

  const send = async (p = phone) => {
    setBusy(true);
    setError(null);
    try {
      const r = await api("/v1/auth/otp/send", { body: { phone: p } });
      setPhone(p);
      setIsNew(!r.existing_user);
      setDevOtp(r.dev_otp || null);
      setOtp("");
      setStep("otp");
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setBusy(false);
    }
  };

  const verify = async (e?: React.FormEvent) => {
    e?.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api("/v1/auth/otp/verify", { body: { phone, otp, role: isNew ? role : null } });
      signIn(r);
      router.replace(params.get("next") || homeFor(r.user));
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login">
      <section className="login-art">
        <Logo />
        <div className="stack-lg" style={{ gap: 18 }}>
          <h1>Paid per verified view.</h1>
          <p>
            Brands fund briefs into escrow. Creators post Reels and Shorts from their own accounts and get paid as views are
            verified. Every post makes your Creator Score sharper.
          </p>
        </div>
        <div className="stack" style={{ gap: 10, color: "#dfe5cd" }}>
          {["Escrow on Razorpay Route, released on approval", "INR payouts with TDS and GST handled",
            "Instagram Reels and YouTube Shorts only"].map((t) => (
            <div key={t} className="row" style={{ gap: 10 }}>
              <Check size={16} strokeWidth={2} color="var(--lime)" /> {t}
            </div>
          ))}
        </div>
      </section>
      <section className="login-form">
        <div className="inner">
          {step === "phone" ? (
            <form className="form" onSubmit={(e) => { e.preventDefault(); send(); }}>
              <div className="stack" style={{ gap: 6 }}>
                <h2 style={{ fontSize: 26, fontWeight: 600 }}>Sign in or sign up</h2>
                <p className="muted">We’ll text a 6-digit code to your phone.</p>
              </div>
              <div className="field">
                <label htmlFor="phone">Mobile number</label>
                <div className="row" style={{ gap: 8 }}>
                  <span className="input" style={{ width: 72, display: "grid", placeItems: "center", background: "var(--surface)" }}>+91</span>
                  <input id="phone" className="input on-ground" inputMode="numeric" autoComplete="tel-national" placeholder="98765 43210"
                    value={phone} onChange={(e) => setPhone(e.target.value)} />
                </div>
              </div>
              <ErrorNote error={error} />
              <button className="btn primary block" disabled={busy || phone.replace(/\D/g, "").length < 10}>
                {busy ? <Spinner /> : <>Continue <ArrowRight size={16} strokeWidth={2} /></>}
              </button>
              <div className="stack" style={{ gap: 8, marginTop: 8 }}>
                <span className="muted small">Demo accounts</span>
                {DEMO.map((d) => (
                  <button type="button" key={d.phone} className="item link-row" style={{ border: 0, textAlign: "left", cursor: "pointer", background: "var(--surface)" }}
                    onClick={() => send(d.phone)}>
                    <div className="grow">
                      <div className="strong">{d.who}</div>
                      <div className="muted small">{d.what}</div>
                    </div>
                    <span className="faint small num">+91 {d.phone.slice(0, 5)} {d.phone.slice(5)}</span>
                  </button>
                ))}
              </div>
            </form>
          ) : (
            <form className="form" onSubmit={verify}>
              <div className="stack" style={{ gap: 6 }}>
                <h2 style={{ fontSize: 26, fontWeight: 600 }}>Enter the code</h2>
                <p className="muted">Sent to {phone.startsWith("+") ? phone : `+91 ${phone}`}. <button type="button" className="link" style={{ border: 0, background: "none", cursor: "pointer", padding: 0 }} onClick={() => setStep("phone")}>Change</button></p>
              </div>
              {devOtp && (
                <div className="banner-dev">
                  <KeyRound size={16} strokeWidth={S} /> Dev mode: your code is <strong className="num">{devOtp}</strong>
                  <button type="button" className="btn sm" style={{ marginLeft: "auto", background: "var(--lime-ink)", color: "var(--lime)" }} onClick={() => setOtp(devOtp)}>Fill</button>
                </div>
              )}
              <input className="input on-ground otp" inputMode="numeric" autoComplete="one-time-code" maxLength={6} aria-label="One-time code"
                value={otp} onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))} autoFocus />
              {isNew && (
                <div className="field">
                  <span className="label">I’m joining as</span>
                  <div className="grid cols-2">
                    {([["creator", "A creator", Camera, "Post and get paid per view"], ["brand_member", "A brand", Building2, "Fund briefs, buy verified views"]] as const).map(([v, l, Icon, d]) => (
                      <button type="button" key={v} onClick={() => setRole(v)} className="card tight"
                        style={{ border: 0, textAlign: "left", cursor: "pointer", outline: role === v ? "2px solid var(--olive)" : "none" }}>
                        <Icon size={20} strokeWidth={S} />
                        <div className="strong" style={{ marginTop: 6 }}>{l}</div>
                        <div className="muted small">{d}</div>
                      </button>
                    ))}
                  </div>
                </div>
              )}
              <ErrorNote error={error} />
              <button className="btn primary block" disabled={busy || otp.length !== 6}>
                {busy ? <Spinner /> : "Verify and continue"}
              </button>
              <button type="button" className="btn ghost" onClick={() => send()} disabled={busy}>Resend code</button>
            </form>
          )}
        </div>
      </section>
    </div>
  );
}

export default function Page() {
  return (
    <Suspense>
      <Login />
    </Suspense>
  );
}
