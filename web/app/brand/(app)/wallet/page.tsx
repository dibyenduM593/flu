"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Download, Plus } from "lucide-react";
import { api, ApiError, download } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { date, datetime, inr, title } from "@/lib/format";
import { useOrg } from "@/lib/org";
import { useSession } from "@/lib/session";
import { Chips, Empty, ErrorNote, Field, Loading, S, Spinner, Stat, Status, Tabs } from "@/components/ui";

const KIND: Record<string, string> = {
  topup: "Top-up", reserve: "Reserved for hire", release_reserve: "Released from reserve", payout: "Paid to creator",
  fee: "Platform fee", fee_gst: "GST on fee", tds_withheld: "TDS withheld", refund: "Refund", adjustment: "Adjustment",
};

function Wallet() {
  const org = useOrg();
  const { toast } = useSession();
  const params = useSearchParams();
  const router = useRouter();
  const { data, error, loading, reload } = useApi<any>(org ? `/v1/orgs/${org.id}/wallet` : null);
  const payouts = useApi<any>(org ? `/v1/orgs/${org.id}/payouts` : null);
  const [amount, setAmount] = useState("50000");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  const [tab, setTab] = useState<"ledger" | "payouts" | "payments">("ledger");

  useEffect(() => {
    if (params.get("paid")) {
      toast("Payment captured. Your wallet is credited.");
      router.replace("/brand/wallet");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const topup = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const r = await api(`/v1/orgs/${org!.id}/wallet/topup`, { body: { amount_paise: Math.round(Number(amount) * 100) }, idempotent: true });
      if (r.checkout_url) window.location.href = r.checkout_url;
      else toast("Order created. Complete payment in Razorpay Checkout.");
    } catch (e) {
      setErr(e as ApiError);
      setBusy(false);
    }
  };
  if (loading && !data) return <Loading />;
  if (error) return <ErrorNote error={error} />;
  const s = data.summary;
  return (
    <>
      <div className="page-title">
        <div><h1>Wallet</h1><p>Money sits in Razorpay’s escrow flow, not in Flu’s bank account. It moves in four steps: top-up, reserve on hire, accrue on verified views, release on approval.</p></div>
        <button className="btn" onClick={() => download(`/v1/orgs/${org!.id}/payouts/export`, `flu-payouts.csv`).catch((e) => toast(e.message, "error"))}>
          <Download size={16} strokeWidth={S} /> Export payouts for your CA
        </button>
      </div>
      <div className="grid cols-4">
        <Stat k="Available" v={inr(s.available_paise)} d="Funds new hires" />
        <Stat k="Held in escrow" v={inr(s.reserved_paise)} d="Reserved for hired creators" />
        <Stat k="Paid to creators" v={inr(s.paid_to_creators_paise)} d={`TDS ${inr(s.tds_paise)} withheld`} />
        <Stat k="Platform fee" v={inr(s.fees_paise)} d={`+ ${inr(s.fee_gst_paise)} GST, invoiced`} />
      </div>
      <div className="grid split-r">
        <form className="card form" onSubmit={topup}>
          <h2 style={{ fontSize: 18, fontWeight: 600 }}>Add money</h2>
          <Chips onSurface value={amount} onChange={setAmount} items={["10000", "25000", "50000", "100000"].map((v) => ({ id: v, label: inr(Number(v) * 100) }))} />
          <Field label="Amount (₹)" hint="Minimum ₹5,000. GSTIN is needed above ₹50,000. UPI, cards and net banking via Razorpay.">
            <input className="input" inputMode="numeric" value={amount} onChange={(e) => setAmount(e.target.value.replace(/\D/g, ""))} />
          </Field>
          <ErrorNote error={err} />
          <button className="btn primary" disabled={busy || Number(amount) < 5000}>{busy ? <Spinner /> : <><Plus size={16} strokeWidth={2} /> Pay {inr(Number(amount) * 100)}</>}</button>
          <p className="faint small">Unused money is refundable within 7 days of a top-up.</p>
        </form>
        <section className="card">
          <Tabs value={tab} onChange={setTab} items={[{ id: "ledger", label: "Ledger" }, { id: "payouts", label: "Payouts" }, { id: "payments", label: "Top-ups" }]} />
          <div style={{ marginTop: 14 }}>
            {tab === "ledger" && (data.entries.length ? (
              <div className="table-wrap"><table>
                <thead><tr><th>When</th><th>Entry</th><th className="r">Amount</th></tr></thead>
                <tbody>{data.entries.map((e: any) => (
                  <tr key={e.id}><td className="nowrap muted">{datetime(e.created_at)}</td><td>{KIND[e.kind] || title(e.kind)}<span className="sub">{e.memo}</span></td>
                    <td className="r num strong" style={{ color: e.amount_paise > 0 ? "var(--good)" : undefined }}>{e.amount_paise > 0 ? "+" : "−"}{inr(Math.abs(e.amount_paise), { decimals: true })}</td></tr>
                ))}</tbody>
              </table></div>
            ) : <Empty title="No entries yet" />)}
            {tab === "payouts" && (payouts.data?.data.length ? (
              <div className="table-wrap"><table>
                <thead><tr><th>Invoice</th><th>Creator</th><th className="r">Gross</th><th className="r">Fee + GST</th><th className="r">TDS</th><th>Status</th></tr></thead>
                <tbody>{payouts.data.data.map((p: any) => (
                  <tr key={p.id}><td className="nowrap">{p.invoice_no || "—"}<span className="sub">{date(p.created_at)}</span></td><td>{p.creator}<span className="sub">{p.brief_title}</span></td>
                    <td className="r num">{inr(p.gross_paise, { decimals: true })}</td><td className="r num">{inr(p.fee_paise + p.gst_paise, { decimals: true })}</td>
                    <td className="r num">{inr(p.tds_paise, { decimals: true })}</td><td><Status s={p.status} /></td></tr>
                ))}</tbody>
              </table></div>
            ) : <Empty title="No payouts yet" />)}
            {tab === "payments" && (data.payments.length ? (
              <div className="items">{data.payments.map((p: any) => (
                <div key={p.id} className="item"><div className="grow"><div className="strong num">{inr(p.amount_paise)}</div><div className="muted small">{p.order_id} · {datetime(p.created_at)}</div></div><Status s={p.status} /></div>
              ))}</div>
            ) : <Empty title="No top-ups yet" />)}
          </div>
        </section>
      </div>
    </>
  );
}

export default function Page() {
  return <Suspense><Wallet /></Suspense>;
}
