"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";
import { GuardedBare } from "@/components/Guarded";
import { ErrorNote, Field, Logo, Spinner } from "@/components/ui";

function Onboarding() {
  const { refreshMe } = useSession();
  const router = useRouter();
  const [f, setF] = useState({ name: "", instagram_handle: "", category: "", city: "", website: "", gstin: "", description: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api("/v1/orgs", { body: f });
      await refreshMe();
      router.replace("/brand/briefs/new");
    } catch (e) {
      setErr(e as ApiError);
      setBusy(false);
    }
  };
  return (
    <div style={{ minHeight: "100dvh", display: "grid", placeItems: "center", padding: 16 }}>
      <form className="card form" style={{ width: "min(560px, 100%)", padding: 28 }} onSubmit={submit}>
        <Logo sub="for brands" />
        <div className="stack" style={{ gap: 6 }}>
          <h1 style={{ fontSize: 26, fontWeight: 600 }}>Create your workspace</h1>
          <p className="muted">Ten minutes to your first brief. Pay per verified view, no minimum spend.</p>
        </div>
        <div className="form-row">
          <Field label="Brand name"><input className="input" value={f.name} onChange={set("name")} /></Field>
          <Field label="Instagram handle"><input className="input" value={f.instagram_handle} onChange={set("instagram_handle")} placeholder="@yourbrand" /></Field>
        </div>
        <Field label="What you sell"><input className="input" value={f.description} onChange={set("description")} placeholder="Ayurvedic skincare, made in small batches" /></Field>
        <div className="form-row">
          <Field label="Category"><input className="input" value={f.category} onChange={set("category")} placeholder="Beauty and personal care" /></Field>
          <Field label="City"><input className="input" value={f.city} onChange={set("city")} /></Field>
        </div>
        <div className="form-row">
          <Field label="Website"><input className="input" value={f.website} onChange={set("website")} /></Field>
          <Field label="GSTIN (optional now)" hint="Needed before a top-up above ₹50,000."><input className="input" value={f.gstin} onChange={set("gstin")} /></Field>
        </div>
        <ErrorNote error={err} />
        <button className="btn primary" disabled={busy || f.name.trim().length < 2}>{busy ? <Spinner /> : "Create workspace"}</button>
      </form>
    </div>
  );
}

export default function Page() {
  return <GuardedBare role="brand_member"><Onboarding /></GuardedBare>;
}
