"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { CITIES } from "@/lib/format";
import { useSession } from "@/lib/session";
import { GuardedBare } from "@/components/Guarded";
import { ErrorNote, Field, Logo, Spinner } from "@/components/ui";

function Onboarding() {
  const { refreshMe } = useSession();
  const router = useRouter();
  const [f, setF] = useState({ display_name: "", city: "", bio: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api("/v1/creator/profile", { body: f });
      await refreshMe();
      router.replace("/creator/accounts");
    } catch (e) {
      setErr(e as ApiError);
      setBusy(false);
    }
  };
  return (
    <div style={{ minHeight: "100dvh", display: "grid", placeItems: "center", padding: 16 }}>
      <form className="card form" style={{ width: "min(480px, 100%)", padding: 28 }} onSubmit={submit}>
        <Logo sub="for creators" />
        <div className="stack" style={{ gap: 6 }}>
          <h1 style={{ fontSize: 26, fontWeight: 600 }}>Set up your profile</h1>
          <p className="muted">Brands see this next to your Creator Score. No follower minimum: a connected account and a passing audit are enough.</p>
        </div>
        <Field label="Name brands will see" htmlFor="dn"><input id="dn" className="input" value={f.display_name} onChange={(e) => setF({ ...f, display_name: e.target.value })} /></Field>
        <Field label="City" htmlFor="city">
          <input id="city" className="input" list="cities" value={f.city} onChange={(e) => setF({ ...f, city: e.target.value })} placeholder="Pune" />
          <datalist id="cities">{CITIES.map((c) => <option key={c} value={c} />)}</datalist>
        </Field>
        <Field label="One line about your content (optional)" htmlFor="bio"><input id="bio" className="input" value={f.bio} onChange={(e) => setF({ ...f, bio: e.target.value })} /></Field>
        <ErrorNote error={err} />
        <button className="btn primary" disabled={busy || f.display_name.trim().length < 2}>{busy ? <Spinner /> : "Continue to connect an account"}</button>
      </form>
    </div>
  );
}

export default function Page() {
  return <GuardedBare role="creator"><Onboarding /></GuardedBare>;
}
