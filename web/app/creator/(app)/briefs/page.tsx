"use client";

import { useState } from "react";
import { useApi } from "@/lib/hooks";
import { NICHES, title } from "@/lib/format";
import { BriefCard } from "@/components/creator";
import { Chips, Empty, ErrorNote, Loading } from "@/components/ui";

export default function Briefs() {
  const [pay, setPay] = useState<"" | "cpm" | "flat" | "hybrid">("");
  const [niche, setNiche] = useState("");
  const q = new URLSearchParams();
  if (pay) q.set("pay_model", pay);
  if (niche) q.set("niche", niche);
  const { data, error, loading } = useApi<any>(`/v1/creator/briefs?${q}`);
  return (
    <>
      <div className="page-title">
        <div>
          <h1>Open briefs</h1>
          <p>Ranked by what you’re likely to earn, from your median views and each brief’s rate.</p>
        </div>
        <select className="select" style={{ width: 220, background: "var(--surface)" }} value={niche} onChange={(e) => setNiche(e.target.value)} aria-label="Niche">
          <option value="">All niches</option>
          {NICHES.map((n) => <option key={n} value={n}>{title(n)}</option>)}
        </select>
      </div>
      <Chips value={pay} onChange={setPay} items={[{ id: "", label: "All pay types" }, { id: "cpm", label: "Per view" }, { id: "hybrid", label: "Base + per view" }, { id: "flat", label: "Flat fee" }]} />
      <ErrorNote error={error} />
      {loading && !data ? <Loading /> : data && (
        <>
          {data.data.length ? (
            <div className="grid cols-3">{data.data.map((b: any) => <BriefCard key={b.id} b={b} />)}</div>
          ) : (
            <div className="card"><Empty title="Nothing open for you with these filters" /></div>
          )}
          {data.locked.length > 0 && (
            <section className="stack" style={{ marginTop: 12 }}>
              <div className="page-title"><div><h1 style={{ fontSize: 20 }}>Not open to you yet</h1><p>What’s missing is listed on each brief. Most of it is your tier.</p></div></div>
              <div className="grid cols-3">{data.locked.map((b: any) => <BriefCard key={b.id} b={b} locked />)}</div>
            </section>
          )}
        </>
      )}
    </>
  );
}
