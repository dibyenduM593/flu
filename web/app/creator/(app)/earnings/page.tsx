"use client";

import { useState } from "react";
import { ShieldCheck } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { date, inr, num } from "@/lib/format";
import { useSession } from "@/lib/session";
import { Empty, ErrorNote, Field, Loading, S, Spinner, Stat, Status, Tabs } from "@/components/ui";

function KycForm({ onDone }: { onDone: () => void }) {
  const { toast, refreshMe } = useSession();
  const [f, setF] = useState({ pan: "", name: "", method: "upi", vpa: "", ifsc: "", account_number: "", gstin: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await api("/v1/creator/kyc", { body: {
        pan: f.pan, name: f.name, gstin: f.gstin || null,
        ...(f.method === "upi" ? { vpa: f.vpa } : { ifsc: f.ifsc, account_number: f.account_number }),
      } });
      toast("Verified. Held earnings are on their way.");
      refreshMe();
      onDone();
    } catch (e) {
      setErr(e as ApiError);
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="card form" id="kyc" onSubmit={submit}>
      <div className="row"><ShieldCheck size={20} strokeWidth={S} /><h2 style={{ fontSize: 18, fontWeight: 600 }}>Get paid: PAN and payout account</h2></div>
      <p className="muted small">Required by law before the first payout. We store only a hash of your PAN and its last four characters; your bank details stay with Razorpay.</p>
      <div className="form-row">
        <Field label="PAN" htmlFor="pan"><input id="pan" className="input" style={{ textTransform: "uppercase" }} maxLength={10} placeholder="ABCDE1234F" value={f.pan} onChange={set("pan")} /></Field>
        <Field label="Name as on PAN" htmlFor="pname"><input id="pname" className="input" value={f.name} onChange={set("name")} /></Field>
      </div>
      <div className="tabs" style={{ background: "var(--surface-2)" }}>
        {[["upi", "UPI ID"], ["bank", "Bank account"]].map(([k, l]) => (
          <button type="button" key={k} aria-selected={f.method === k} onClick={() => setF({ ...f, method: k })}>{l}</button>
        ))}
      </div>
      {f.method === "upi" ? (
        <Field label="UPI ID"><input className="input" placeholder="name@okhdfcbank" value={f.vpa} onChange={set("vpa")} /></Field>
      ) : (
        <div className="form-row">
          <Field label="IFSC"><input className="input" style={{ textTransform: "uppercase" }} placeholder="HDFC0001234" value={f.ifsc} onChange={set("ifsc")} /></Field>
          <Field label="Account number"><input className="input" inputMode="numeric" value={f.account_number} onChange={set("account_number")} /></Field>
        </div>
      )}
      <Field label="GSTIN (only if you are GST-registered)"><input className="input" value={f.gstin} onChange={set("gstin")} /></Field>
      <ErrorNote error={err} />
      <button className="btn primary" disabled={busy || f.pan.length !== 10 || !f.name}>{busy ? <Spinner /> : "Verify"}</button>
    </form>
  );
}

export default function Earnings() {
  const { data, error, loading, reload } = useApi<any>("/v1/creator/earnings");
  const [tab, setTab] = useState<"payouts" | "accruing">("payouts");
  if (loading && !data) return <Loading />;
  if (error) return <ErrorNote error={error} />;
  const t = data.totals;
  const kyc = data.kyc;
  return (
    <>
      <div className="page-title"><div><h1>Earnings</h1><p>Approved → settling (1 to 3 days on Razorpay Route) → paid to your bank or UPI.</p></div></div>
      <div className="grid cols-4">
        <Stat k="Accruing on live posts" v={inr(t.accrued_paise)} d="Released once approved" />
        <Stat k="Settling" v={inr(t.settling_paise)} d="Arrives in 1 to 3 days" />
        <Stat k="Paid" v={inr(t.paid_paise)} d="Net of fee and TDS" />
        <Stat k="TDS withheld" v={inr(t.tds_paise)} d="Section 194-O, Form 16A quarterly" />
      </div>
      {t.held_kyc_paise > 0 && <div className="note warn">{inr(t.held_kyc_paise)} is approved and waiting for your KYC.</div>}
      {data.gst_warning && <div className="note warn">You’ve earned over ₹15 lakh this year. Above ₹20 lakh you must register for GST.</div>}
      {kyc.status !== "verified" ? <KycForm onDone={reload} /> : (
        <section className="card row wrap-row" style={{ gap: 20 }}>
          <ShieldCheck size={22} strokeWidth={S} color="var(--good)" />
          <div className="grow">
            <div className="strong">KYC verified</div>
            <div className="muted small">PAN ••••••{kyc.pan_last4} · {kyc.vpa ? `UPI ${kyc.vpa}` : `Bank ••••${kyc.account_tail} (${kyc.ifsc})`}</div>
          </div>
          <Status s="verified" />
        </section>
      )}
      <Tabs value={tab} onChange={setTab} items={[{ id: "payouts", label: "Payouts", count: data.payouts.length }, { id: "accruing", label: "Accruing", count: data.lines.length }]} />
      <section className="card">
        {tab === "payouts" ? (data.payouts.length ? (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Brief</th><th>Date</th><th className="r">Earned</th><th className="r">Platform fee</th><th className="r">TDS</th><th className="r">You get</th><th>Status</th></tr></thead>
              <tbody>
                {data.payouts.map((p: any) => (
                  <tr key={p.id}>
                    <td>{p.brief_title}<span className="sub">{p.invoice_no || p.hold_reason?.replace("_", " ")}</span></td>
                    <td className="nowrap">{date(p.created_at)}</td>
                    <td className="r num">{inr(p.gross_paise, { decimals: true })}</td>
                    <td className="r num muted">−{inr(p.fee_paise, { decimals: true })}</td>
                    <td className="r num muted">−{inr(p.tds_paise, { decimals: true })}</td>
                    <td className="r num strong">{inr(p.net_paise, { decimals: true })}</td>
                    <td><Status s={p.status} />{p.utr && <span className="sub">UTR {p.utr}</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <Empty title="No payouts yet">Once a brand approves your post, earnings release here.</Empty>) : (data.lines.length ? (
          <div className="items">
            {data.lines.map((l: any) => (
              <div key={l.deliverable_id} className="item">
                <div className="grow"><div className="strong">{l.brief_title}</div><div className="muted small">{l.brand} · {num(l.verified_views)} verified views</div></div>
                <Status s={l.status} />
                <strong className="num">{inr(l.gross_paise)}</strong>
              </div>
            ))}
          </div>
        ) : <Empty title="Nothing accruing right now" />)}
      </section>
    </>
  );
}
