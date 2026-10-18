"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import {
  Activity, Bell, Briefcase, Building2, CircleDollarSign, ClipboardCheck, Clock, Gauge, Home, LayoutGrid, Link2,
  LogOut, Megaphone, ShieldAlert, Sparkles, Users, Wallet, Wand2,
} from "lucide-react";
import { api } from "@/lib/api";
import { initials, rel } from "@/lib/format";
import { Me, useSession } from "@/lib/session";
import { Logo, S } from "./ui";

type NavItem = { href: string; label: string; icon: React.ComponentType<any>; mobile?: boolean };

const NAV: Record<string, NavItem[]> = {
  creator: [
    { href: "/creator", label: "Home", icon: Home, mobile: true },
    { href: "/creator/briefs", label: "Briefs", icon: Megaphone, mobile: true },
    { href: "/creator/work", label: "My work", icon: Briefcase, mobile: true },
    { href: "/creator/studio", label: "Studio", icon: Wand2, mobile: true },
    { href: "/creator/earnings", label: "Earnings", icon: CircleDollarSign, mobile: true },
    { href: "/creator/score", label: "Creator Score", icon: Gauge },
    { href: "/creator/accounts", label: "Accounts", icon: Link2 },
  ],
  brand_member: [
    { href: "/brand", label: "Overview", icon: LayoutGrid, mobile: true },
    { href: "/brand/briefs", label: "Briefs", icon: Megaphone, mobile: true },
    { href: "/brand/creators", label: "Creators", icon: Users, mobile: true },
    { href: "/brand/wallet", label: "Wallet", icon: Wallet, mobile: true },
    { href: "/brand/settings", label: "Workspace", icon: Building2, mobile: true },
  ],
  ops: [
    { href: "/ops", label: "Trust queue", icon: ShieldAlert, mobile: true },
    { href: "/ops/system", label: "Simulator", icon: Clock, mobile: true },
    { href: "/ops/ai", label: "AI and evals", icon: Sparkles, mobile: true },
    { href: "/ops/audit", label: "Audit log", icon: ClipboardCheck, mobile: true },
  ],
};

const ROLE_SUB: Record<string, string> = { creator: "for creators", brand_member: "for brands", ops: "ops" };

function isActive(path: string, href: string, root: string) {
  return href === root ? path === root : path === href || path.startsWith(href + "/");
}

function Notifications() {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<any>(null);
  const ref = useRef<HTMLDivElement>(null);
  const router = useRouter();
  const load = () => api("/v1/me/notifications").then(setData).catch(() => {});
  useEffect(() => {
    load();
    const t = setInterval(load, 20000);
    return () => clearInterval(t);
  }, []);
  useEffect(() => {
    const h = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);
  const toggle = async () => {
    setOpen(!open);
    if (!open && data?.unread) {
      await api("/v1/me/notifications/read", { method: "POST" }).catch(() => {});
      setTimeout(load, 400);
    }
  };
  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button className="icon-btn" onClick={toggle} aria-label={`Notifications${data?.unread ? `, ${data.unread} unread` : ""}`} aria-expanded={open}>
        <Bell size={19} strokeWidth={S} />
        {!!data?.unread && <span className="dot" />}
      </button>
      {open && (
        <div className="popover" role="menu">
          <div className="row between" style={{ padding: "6px 10px 8px" }}>
            <strong>Notifications</strong>
          </div>
          {!data?.data?.length && <p className="muted small" style={{ padding: "8px 12px 14px" }}>Nothing yet.</p>}
          {data?.data?.map((n: any) => (
            <button key={n.id} className={`n ${n.read ? "" : "unread"}`} style={{ border: 0, textAlign: "left", cursor: n.link ? "pointer" : "default", background: undefined }}
              onClick={() => { if (n.link) { setOpen(false); router.push(n.link); } }}>
              <span className="strong" style={{ fontSize: 14 }}>{n.title}</span>
              {n.body && <span className="muted small">{n.body}</span>}
              <span className="faint small">{rel(n.created_at)}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function displayName(me: Me) {
  if (me.role === "creator") return me.creator?.display_name || "Creator";
  if (me.role === "brand_member") return me.orgs[0]?.name || "Brand";
  return "Flu ops";
}

export function Shell({ children, greeting, sub }: { children: React.ReactNode; greeting?: string; sub?: string }) {
  const { me, signOut } = useSession();
  const path = usePathname();
  const router = useRouter();
  if (!me) return null;
  const items = NAV[me.role];
  const root = items[0].href;
  const name = displayName(me);
  return (
    <div className="shell">
      <aside className="side">
        <Link href={root}><Logo sub={ROLE_SUB[me.role]} /></Link>
        <nav className="side-nav" aria-label="Main">
          {items.map((i) => (
            <Link key={i.href} href={i.href} aria-current={isActive(path, i.href, root) ? "page" : undefined}>
              <i.icon size={19} strokeWidth={S} />
              {i.label}
            </Link>
          ))}
        </nav>
        <div className="side-foot">
          <div className="row" style={{ padding: "0 6px" }}>
            <div className="avatar sm">{initials(name)}</div>
            <div className="grow">
              <div className="strong small ellipsis">{name}</div>
              <div className="faint small">{me.phone}</div>
            </div>
          </div>
          <button className="btn ghost sm" style={{ justifyContent: "flex-start" }} onClick={() => { signOut(); router.replace("/"); }}>
            <LogOut size={16} strokeWidth={S} /> Sign out
          </button>
        </div>
      </aside>
      <main className="main">
        <div className="wrap">
          <header className="topbar">
            <div className="hello">
              <div className="avatar">{initials(name)}</div>
              <div style={{ minWidth: 0 }}>
                <h1 className="ellipsis">{greeting ?? (me.role === "creator" ? `Hello, ${name.split(" ")[0]}` : name)}</h1>
                <p className="ellipsis">{sub ?? (me.role === "ops" ? "Keep fraud out and payouts correct" : "")}</p>
              </div>
            </div>
            <div className="row" style={{ gap: 8 }}>
              {me.role === "ops" && <Link className="icon-btn" href="/ops/system" aria-label="Simulator"><Activity size={19} strokeWidth={S} /></Link>}
              <Notifications />
              <button className="icon-btn hide-desktop" onClick={() => { signOut(); router.replace("/"); }} aria-label="Sign out">
                <LogOut size={18} strokeWidth={S} />
              </button>
            </div>
          </header>
          {children}
        </div>
      </main>
      <nav className="bottom-nav" aria-label="Main">
        {items.filter((i) => i.mobile).slice(0, 5).map((i) => (
          <Link key={i.href} href={i.href} aria-current={isActive(path, i.href, root) ? "page" : undefined}>
            <span className="ico-wrap"><i.icon size={20} strokeWidth={S} /></span>
            {i.label}
          </Link>
        ))}
      </nav>
    </div>
  );
}
