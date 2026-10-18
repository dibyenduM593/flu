"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { useOrg } from "@/lib/org";
import { useSession } from "@/lib/session";
import { ErrorNote, Field, Loading, Spinner } from "@/components/ui";

const PLANS = [
  { id: "starter", name: "Starter", price: "Free", take: "15% platform fee", live: "5 creators live" },
  { id: "growth", name: "Growth", price: "₹4,999 a month", take: "10% platform fee", live: "50 creators live" },
  { id: "scale", name: "Scale", price: "₹14,999 a month", take: "No platform fee", live: "Unlimited" },
];

export default function Settings() {
  const org = useOrg();
  const { toast, refreshMe } = useSession();
  const { data, loading, reload } = useApi<any>(org ? `/v1/orgs/${org.id}` : null);
  const members = useApi<any>(org ? `/v1/orgs/${org.id}/members` : null);
  const [f, setF] = useState<any>(null);
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  useEffect(() => { if (data) setF(data); }, [data]);
  if (loading || !f) return <Loading />;
  const save = async (patch: any) => {
    setBusy(true);
    setErr(null);
    try {
      await api(`/v1/orgs/${org!.id}`, { method: "PATCH", body: patch });
      toast("Saved");
      reload();
      refreshMe();
    } catch (e) {
      setErr(e as ApiError);
    } finally {
      setBusy(false);
    }
  };
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setF({ ...f, [k]: e.target.value });
  return (
    <>
      <div className="page-title"><div><h1>Workspace</h1><p>What creators see before they apply, and the details that go on your invoices.</p></div></div>
      <div className="grid split">
        <form className="card form" onSubmit={(e) => { e.preventDefault(); save({ name: f.name, gstin: f.gstin, pan: f.pan, category: f.category, city: f.city, website: f.website, instagram_handle: f.instagram_handle, description: f.description }); }}>
          <div className="form-row">
            <Field label="Brand name"><input className="input" value={f.name || ""} onChange={set("name")} /></Field>
            <Field label="Instagram handle" hint="Used as the required @mention on briefs."><input className="input" value={f.instagram_handle || ""} onChange={set("instagram_handle")} /></Field>
          </div>
          <Field label="What you sell"><textarea className="textarea" value={f.description || ""} onChange={set("description")} /></Field>
          <div className="form-row">
            <Field label="Category"><input className="input" value={f.category || ""} onChange={set("category")} /></Field>
            <Field label="City"><input className="input" value={f.city || ""} onChange={set("city")} /></Field>
          </div>
          <div className="form-row three">
            <Field label="Website"><input className="input" value={f.website || ""} onChange={set("website")} /></Field>
            <Field label="GSTIN"><input className="input" value={f.gstin || ""} onChange={set("gstin")} /></Field>
            <Field label="PAN"><input className="input" value={f.pan || ""} onChange={set("pan")} /></Field>
          </div>
          <ErrorNote error={err} />
          <div><button className="btn primary" disabled={busy}>{busy ? <Spinner /> : "Save"}</button></div>
        </form>
        <div className="stack-lg">
          <section className="card stack">
            <h2 style={{ fontSize: 18, fontWeight: 600 }}>Plan</h2>
            {PLANS.map((p) => (
              <button key={p.id} className="item link-row" style={{ border: 0, cursor: "pointer", textAlign: "left", outline: f.plan === p.id ? "2px solid var(--olive)" : "none" }}
                onClick={() => f.plan !== p.id && save({ plan: p.id })}>
                <div className="grow"><div className="strong">{p.name} <span className="muted" style={{ fontWeight: 400 }}>· {p.price}</span></div><div className="muted small">{p.take} · {p.live}</div></div>
                {f.plan === p.id && <span className="tag good">Current</span>}
              </button>
            ))}
            <p className="faint small">Billing for paid plans is not wired in this build; switching changes the take rate on new payouts.</p>
          </section>
          <section className="card stack">
            <h2 style={{ fontSize: 18, fontWeight: 600 }}>Team</h2>
            <div className="items">{members.data?.data.map((m: any) => <div key={m.user_id} className="item"><span className="grow num">{m.phone}</span><span className="tag">{m.role}</span></div>)}</div>
            <form className="row" onSubmit={async (e) => { e.preventDefault(); try { await api(`/v1/orgs/${org!.id}/members`, { body: { phone } }); setPhone(""); members.reload(); toast("Added"); } catch (er: any) { toast(er.message, "error"); } }}>
              <input className="input" placeholder="Teammate’s mobile number" value={phone} onChange={(e) => setPhone(e.target.value)} />
              <button className="btn" disabled={phone.length < 10}>Add</button>
            </form>
          </section>
        </div>
      </div>
    </>
  );
}
