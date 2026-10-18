"use client";

// 127.0.0.1 rather than localhost: on Windows "localhost" tries IPv6 first and stalls ~2 s per request.
export const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details: Record<string, unknown> = {}) {
    super(message);
  }
}

const KEY = "flu.tokens";
type Tokens = { access_token: string; refresh_token: string };

export function getTokens(): Tokens | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Tokens) : null;
  } catch {
    return null;
  }
}

export function setTokens(t: Tokens | null) {
  try {
    if (t) localStorage.setItem(KEY, JSON.stringify({ access_token: t.access_token, refresh_token: t.refresh_token }));
    else localStorage.removeItem(KEY);
  } catch {
    /* storage unavailable: session lasts for this tab only */
  }
}

let refreshing: Promise<boolean> | null = null;

async function refresh(): Promise<boolean> {
  const t = getTokens();
  if (!t) return false;
  refreshing ??= fetch(`${API}/v1/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: t.refresh_token }),
  })
    .then(async (r) => {
      if (!r.ok) {
        setTokens(null);
        return false;
      }
      setTokens(await r.json());
      return true;
    })
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

type Opts = { method?: string; body?: unknown; idempotent?: boolean; raw?: boolean };

export function newKey() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : String(Date.now() + Math.random());
}

export async function api<T = any>(path: string, opts: Opts = {}, retry = true): Promise<T> {
  const headers: Record<string, string> = {};
  const t = getTokens();
  if (t) headers.Authorization = `Bearer ${t.access_token}`;
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (opts.idempotent) headers["Idempotency-Key"] = newKey();
  const res = await fetch(`${API}${path}`, {
    method: opts.method || (opts.body !== undefined ? "POST" : "GET"),
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  if (res.status === 401 && retry && t) {
    if (await refresh()) return api<T>(path, opts, false);
  }
  if (!res.ok) {
    let err: any = {};
    try {
      err = (await res.json()).error || {};
    } catch {
      /* non-JSON error */
    }
    throw new ApiError(res.status, err.code || "error", err.message || `Request failed (${res.status})`, err.details || {});
  }
  if (opts.raw) return (await res.text()) as T;
  return res.json() as Promise<T>;
}

export async function download(path: string, filename: string) {
  const text = await api<string>(path, { raw: true });
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
