"use client";

import { useApi } from "@/lib/hooks";
import { datetime } from "@/lib/format";
import { ErrorNote, Loading } from "@/components/ui";

export default function Audit() {
  const { data, error, loading } = useApi<any>("/v1/ops/audit-log");
  if (loading && !data) return <Loading />;
  if (error) return <ErrorNote error={error} />;
  return (
    <>
      <div className="page-title"><div><h1>Audit log</h1><p>Every money movement and status change, with the actor. Append-only.</p></div></div>
      <section className="card">
        <div className="table-wrap"><table>
          <thead><tr><th>When</th><th>Action</th><th>Entity</th><th>Detail</th></tr></thead>
          <tbody>{data.data.map((r: any) => (
            <tr key={r.id}>
              <td className="nowrap muted small">{datetime(r.at)}</td>
              <td><strong>{r.action}</strong><span className="sub">{r.actor_id ? `by ${r.actor_id.slice(0, 8)}` : "system"}</span></td>
              <td className="small">{r.entity_type}<span className="sub">{r.entity_id.slice(0, 8)}</span></td>
              <td className="small muted" style={{ maxWidth: 420 }}>{r.after ? Object.entries(r.after).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join(" · ") : ""}</td>
            </tr>
          ))}</tbody>
        </table></div>
      </section>
    </>
  );
}
