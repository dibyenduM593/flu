const IN = "en-IN";

export const inr = (paise: number | null | undefined, opts: { decimals?: boolean } = {}) => {
  if (paise == null) return "—";
  const r = paise / 100;
  return "₹" + r.toLocaleString(IN, { maximumFractionDigits: opts.decimals ? 2 : 0, minimumFractionDigits: opts.decimals ? 2 : 0 });
};

/** ₹1.2L / ₹3.4Cr / ₹12K for compact money. */
export const inrShort = (paise: number | null | undefined) => {
  if (paise == null) return "—";
  const r = paise / 100;
  if (Math.abs(r) >= 1e7) return "₹" + (r / 1e7).toFixed(1).replace(/\.0$/, "") + "Cr";
  if (Math.abs(r) >= 1e5) return "₹" + (r / 1e5).toFixed(1).replace(/\.0$/, "") + "L";
  if (Math.abs(r) >= 1e3) return "₹" + (r / 1e3).toFixed(1).replace(/\.0$/, "") + "K";
  return "₹" + Math.round(r);
};

export const num = (n: number | null | undefined) => (n == null ? "—" : Math.round(n).toLocaleString(IN));

export const short = (n: number | null | undefined) => {
  if (n == null) return "—";
  if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, "") + "M";
  if (Math.abs(n) >= 1e3) return (n / 1e3).toFixed(n < 1e4 ? 1 : 0).replace(/\.0$/, "") + "K";
  return String(Math.round(n));
};

export const pct = (x: number | null | undefined, d = 1) => (x == null ? "—" : (x * 100).toFixed(d) + "%");

export const cpm = (paise: number | null | undefined) => (paise == null ? "—" : inr(paise, { decimals: paise % 100 !== 0 }) + " CPM");

const dtf = new Intl.DateTimeFormat(IN, { day: "numeric", month: "short", timeZone: "Asia/Kolkata" });
const dtt = new Intl.DateTimeFormat(IN, { day: "numeric", month: "short", hour: "numeric", minute: "2-digit", timeZone: "Asia/Kolkata" });

export const date = (s: string | null | undefined) => (s ? dtf.format(new Date(s)) : "—");
export const datetime = (s: string | null | undefined) => (s ? dtt.format(new Date(s)) : "—");

/** Offset between the platform clock (which ops can move forward in dev) and this browser's clock. */
let clockSkewMs = 0;
export const setClockSkew = (ms: number) => { clockSkewMs = ms; };
export const platformNow = () => Date.now() + clockSkewMs;

/** Relative to a reference time, by default the platform clock. */
export const rel = (s: string | null | undefined, now?: string | number | Date) => {
  if (!s) return "—";
  const ref = now ? new Date(now).getTime() : platformNow();
  const diff = new Date(s).getTime() - ref;
  const abs = Math.abs(diff);
  const h = abs / 36e5;
  const fmt = (v: number, unit: string) => `${Math.round(v)} ${unit}${Math.round(v) === 1 ? "" : "s"}`;
  const txt = h < 1 ? fmt(abs / 6e4, "min") : h < 48 ? fmt(h, "hour") : fmt(h / 24, "day");
  return diff >= 0 ? `in ${txt}` : `${txt} ago`;
};

export const initials = (name?: string | null) =>
  (name || "?")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join("");

export const title = (s?: string | null) => (s ? s.replace(/[-_]/g, " ").replace(/^\w/, (c) => c.toUpperCase()) : "");

export const PAY_MODEL: Record<string, string> = { cpm: "Per view (CPM)", flat: "Flat fee", hybrid: "Base + per view" };
export const USAGE: Record<string, string> = {
  organic: "Organic only",
  organic_paid_90d: "Organic + paid ads, 90 days",
  paid_perpetual: "Paid ads, perpetual",
};
export const GOAL: Record<string, string> = { awareness: "Awareness", installs: "App installs", orders: "Orders" };

export const payLine = (b: { pay_model: string; cpm_paise: number; flat_paise: number; cap_paise: number }) => {
  if (b.pay_model === "flat") return `${inr(b.flat_paise)} flat per post`;
  if (b.pay_model === "cpm") return `${inr(b.cpm_paise, { decimals: b.cpm_paise % 100 !== 0 })} per 1,000 views, up to ${inr(b.cap_paise)}`;
  return `${inr(b.flat_paise)} base + ${inr(b.cpm_paise, { decimals: b.cpm_paise % 100 !== 0 })} per 1,000 views, up to ${inr(b.cap_paise)}`;
};

export const NICHES = [
  "skincare", "haircare", "makeup", "fashion-women", "fashion-men", "fitness", "food-recipes", "food-reviews",
  "tech-gadgets", "personal-finance", "edtech", "parenting", "travel", "comedy", "gaming", "home-decor",
  "sustainable-living", "wellness", "pets", "books", "music", "dance", "automobiles", "cricket", "photography",
  "art-craft", "career", "productivity", "spirituality", "regional-cinema",
];

export const CITIES = ["Mumbai", "Delhi", "Bengaluru", "Pune", "Hyderabad", "Chennai", "Kolkata", "Jaipur", "Lucknow",
  "Indore", "Kochi", "Ahmedabad", "Chandigarh", "Bhopal", "Nagpur", "Surat"];
