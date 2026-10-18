"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { CreditCard, FlaskConical, Landmark, Smartphone } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { inr } from "@/lib/format";
import { ErrorNote, Logo, S, Spinner } from "@/components/ui";

/** Stand-in for Razorpay Checkout.js when PROVIDER_MODE=fake. */
function Checkout() {
  const p = useSearchParams();
  const router = useRouter();
  const orderId = p.get("order_id");
  const [order, setOrder] = useState<any>(null);
  const [method, setMethod] = useState("upi");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  useEffect(() => { if (orderId) api(`/v1/dev/razorpay/orders/${orderId}`).then(setOrder).catch((e) => setErr(e)); }, [orderId]);
  const pay = async (fail = false) => {
    setBusy(true);
    try {
      const r = await api("/v1/dev/razorpay/pay", { body: { order_id: orderId, method, fail } });
      if (fail) {
        router.replace("/brand/wallet");
        return;
      }
      await api(`/v1/orgs/${order.org_id}/wallet/verify`, { body: r });
      router.replace("/brand/wallet?paid=1");
    } catch (e) {
      setErr(e as ApiError);
      setBusy(false);
    }
  };
  return (
    <div style={{ minHeight: "100dvh", display: "grid", placeItems: "center", padding: 16 }}>
      <div className="card stack-lg" style={{ width: "min(420px, 100%)", padding: 28 }}>
        <div className="banner-dev"><FlaskConical size={16} strokeWidth={S} /> Simulated Razorpay Checkout (dev mode)</div>
        <div className="row between"><Logo size={26} /><span className="muted small">{orderId}</span></div>
        <div>
          <div className="muted small">Wallet top-up</div>
          <div className="big-number">{order ? inr(order.amount) : "…"}</div>
        </div>
        <div className="items">
          {[["upi", "UPI", Smartphone], ["card", "Card", CreditCard], ["netbanking", "Net banking", Landmark]].map(([k, l, I]: any) => (
            <button key={k} className="item link-row" style={{ border: 0, cursor: "pointer", outline: method === k ? "2px solid var(--olive)" : "none" }} onClick={() => setMethod(k)}>
              <I size={18} strokeWidth={S} /><span className="grow" style={{ textAlign: "left" }}>{l}</span>
            </button>
          ))}
        </div>
        <ErrorNote error={err} />
        <button className="btn primary" disabled={busy || !order} onClick={() => pay()}>{busy ? <Spinner /> : `Pay ${order ? inr(order.amount) : ""}`}</button>
        <button className="btn ghost" disabled={busy} onClick={() => pay(true)}>Simulate a failed payment</button>
      </div>
    </div>
  );
}

export default function Page() {
  return <Suspense><Checkout /></Suspense>;
}
