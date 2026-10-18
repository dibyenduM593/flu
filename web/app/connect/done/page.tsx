"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Logo, Spinner } from "@/components/ui";

/** Landing page for the platform OAuth callback. In the consent popup it hands the result to the Accounts page
 *  and closes; opened directly (popup blocked), it redirects there with the result in the query string. */
function Done() {
  const p = useSearchParams();
  const [closedHint, setClosedHint] = useState(false);
  useEffect(() => {
    const result = {
      type: "flu:connect", platform: p.get("platform"), connected: p.get("connected"), handle: p.get("handle"),
      error: p.get("error"), message: p.get("message"),
    };
    if (window.opener && !window.opener.closed) {
      window.opener.postMessage(result, window.location.origin);
      window.close();
      setTimeout(() => setClosedHint(true), 600); // some browsers refuse to close the window
      return;
    }
    const q = new URLSearchParams();
    Object.entries(result).forEach(([k, v]) => { if (v && k !== "type") q.set(k, v); });
    window.location.replace(`/creator/accounts?${q}`);
  }, [p]);
  return (
    <div style={{ minHeight: "100dvh", display: "grid", placeItems: "center", padding: 16 }}>
      <div className="card stack" style={{ width: "min(380px, 100%)", alignItems: "center", textAlign: "center", padding: 28 }}>
        <Logo />
        {closedHint ? <p className="muted">All done. You can close this window.</p> : <div className="row muted" style={{ justifyContent: "center" }}><Spinner /> Finishing up…</div>}
      </div>
    </div>
  );
}

export default function Page() {
  return <Suspense><Done /></Suspense>;
}
