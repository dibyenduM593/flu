"use client";

import { useApi } from "@/lib/hooks";
import { inr, num, title } from "@/lib/format";
import { Empty, ErrorNote, Loading } from "@/components/ui";

export default function Ai() {
  const { data, error, loading } = useApi<any>("/v1/ops/ai/evals");
  if (loading && !data) return <Loading />;
  if (error) return <ErrorNote error={error} />;
  return (
    <>
      <div className="page-title"><div><h1>AI and evals</h1><p>Every model call is logged with its prompt version, tokens, cost and latency. Outside dev mode a prompt version is only served after its eval passes.</p></div></div>
      <section className="card">
        <div className="card-head"><h2>Prompt registry</h2></div>
        <div className="table-wrap"><table>
          <thead><tr><th>Prompt</th><th>Model</th><th>Effort</th><th>Eval set</th><th>Eval</th></tr></thead>
          <tbody>{data.prompts.map((p: any) => (
            <tr key={p.version}><td><strong>{p.version}</strong></td><td>{p.header.model === "main" ? "Main (Sonnet)" : "Fast (Haiku)"}</td><td>{p.header.effort}</td>
              <td className="muted small">{p.header.eval_set}</td>
              <td>{p.header.eval_status === "passed" ? <span className="tag good">Passed</span> : <span className="tag warn">Not run</span>}</td></tr>
          ))}</tbody>
        </table></div>
      </section>
      <section className="card">
        <div className="card-head"><h2>Usage</h2></div>
        {data.usage.length ? (
          <div className="table-wrap"><table>
            <thead><tr><th>Job</th><th>Model</th><th className="r">Calls</th><th className="r">Cost</th><th className="r">Avg latency</th><th className="r">Thumbs up / down</th></tr></thead>
            <tbody>{data.usage.map((u: any, i: number) => (
              <tr key={i}><td>{title(u.kind)}</td><td>{u.model}</td><td className="r num">{num(u.calls)}</td><td className="r num">{inr(u.cost_paise, { decimals: true })}</td>
                <td className="r num">{num(u.avg_latency_ms)} ms</td><td className="r num">{u.thumbs_up} / {u.thumbs_down}</td></tr>
            ))}</tbody>
          </table></div>
        ) : <Empty title="No AI calls yet" />}
      </section>
    </>
  );
}
