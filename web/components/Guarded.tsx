"use client";

import { Me, useGuard, useSession } from "@/lib/session";
import { Shell } from "./Shell";

function Splash() {
  return <div style={{ minHeight: "100dvh", display: "grid", placeItems: "center" }} aria-busy="true" />;
}

export function Guarded({ role, children }: { role: Me["role"]; children: React.ReactNode }) {
  const { ok, me } = useGuard(role);
  if (!ok || !me) return <Splash />;
  let sub: string | undefined;
  if (me.role === "creator" && me.creator) {
    const c = me.creator;
    sub = `${c.tier[0].toUpperCase()}${c.tier.slice(1)} tier · Creator Score ${Math.round(c.score)}`;
  }
  if (me.role === "brand_member") sub = `${me.orgs[0]?.type === "agency" ? "Agency" : "Brand"} workspace · ${me.orgs[0]?.plan[0].toUpperCase()}${me.orgs[0]?.plan.slice(1)} plan`;
  return <Shell sub={sub}>{children}</Shell>;
}

export function GuardedBare({ role, children }: { role: Me["role"]; children: React.ReactNode }) {
  const { ready, me } = useSession();
  useGuard(role, { allowIncomplete: true });
  if (!ready || !me || me.role !== role) return <Splash />;
  return <>{children}</>;
}
