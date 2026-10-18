"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { API, api, ApiError, getTokens, setTokens } from "./api";
import { setClockSkew } from "./format";

export type Me = {
  id: string;
  phone: string;
  role: "creator" | "brand_member" | "ops";
  creator: null | { display_name: string; tier: string; score: number; city: string | null; niches: string[]; kyc_status: string };
  orgs: { id: string; name: string; role: string; plan: string; type: string }[];
};

type Ctx = {
  me: Me | null;
  ready: boolean;
  signIn: (tokens: { access_token: string; refresh_token: string; user: Me }) => void;
  signOut: () => void;
  refreshMe: () => Promise<Me | null>;
  toast: (msg: string, kind?: "ok" | "error") => void;
};

const SessionCtx = createContext<Ctx | null>(null);

export function homeFor(me: Me): string {
  if (me.role === "ops") return "/ops";
  if (me.role === "brand_member") return me.orgs.length ? "/brand" : "/brand/onboarding";
  return me.creator ? "/creator" : "/creator/onboarding";
}

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [ready, setReady] = useState(false);
  const [toastMsg, setToast] = useState<{ msg: string; kind: string } | null>(null);

  const refreshMe = useCallback(async () => {
    if (!getTokens()) {
      setMe(null);
      return null;
    }
    for (let attempt = 0; attempt < 4; attempt++) {
      try {
        const m = await api<Me>("/v1/me");
        setMe(m);
        return m;
      } catch (e) {
        if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
          setTokens(null);
          setMe(null);
          return null;
        }
        // API unreachable (restarting, offline): keep the session and retry.
        await new Promise((r) => setTimeout(r, 1500 * (attempt + 1)));
      }
    }
    return null;
  }, []);

  useEffect(() => {
    refreshMe().finally(() => setReady(true));
    const sync = () => fetch(`${API}/health`).then((r) => r.json()).then((h) => setClockSkew(new Date(h.now).getTime() - Date.now())).catch(() => {});
    sync();
    const t = setInterval(sync, 30000);
    return () => clearInterval(t);
  }, [refreshMe]);

  const toast = useCallback((msg: string, kind: "ok" | "error" = "ok") => {
    setToast({ msg, kind });
    window.clearTimeout((window as any).__fluToast);
    (window as any).__fluToast = window.setTimeout(() => setToast(null), 3200);
  }, []);

  const value = useMemo<Ctx>(
    () => ({
      me,
      ready,
      refreshMe,
      toast,
      signIn: (t) => {
        setTokens(t);
        setMe(t.user);
      },
      signOut: () => {
        setTokens(null);
        setMe(null);
      },
    }),
    [me, ready, refreshMe, toast],
  );

  return (
    <SessionCtx.Provider value={value}>
      {children}
      {toastMsg && (
        <div className={`toast ${toastMsg.kind === "error" ? "error" : ""}`} role="status">
          {toastMsg.msg}
        </div>
      )}
    </SessionCtx.Provider>
  );
}

export function useSession() {
  const c = useContext(SessionCtx);
  if (!c) throw new Error("useSession outside SessionProvider");
  return c;
}

/** Redirects to login when signed out, or to the right home when the role does not match. */
export function useGuard(role: Me["role"], opts: { allowIncomplete?: boolean } = {}) {
  const { me, ready } = useSession();
  const router = useRouter();
  const path = usePathname();
  useEffect(() => {
    if (!ready) return;
    if (!me) {
      router.replace(`/?next=${encodeURIComponent(path)}`);
      return;
    }
    if (me.role !== role) {
      router.replace(homeFor(me));
      return;
    }
    if (!opts.allowIncomplete) {
      if (role === "creator" && !me.creator) router.replace("/creator/onboarding");
      if (role === "brand_member" && !me.orgs.length) router.replace("/brand/onboarding");
    }
  }, [ready, me, role, router, path, opts.allowIncomplete]);
  const ok = ready && !!me && me.role === role && (opts.allowIncomplete || (role === "creator" ? !!me.creator : role === "brand_member" ? me.orgs.length > 0 : true));
  return { me, ok };
}
