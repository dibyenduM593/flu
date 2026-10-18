"use client";

import Link from "next/link";
import { useState } from "react";
import { FileSignature, FlaskConical, Send } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { date, inr, payLine, USAGE } from "@/lib/format";
import { useSession } from "@/lib/session";
import { DeliverableCard } from "@/components/DeliverableCard";
import { Empty, ErrorNote, Field, Loading, Modal, S, Spinner, Status, Tabs } from "@/components/ui";

function ContractModal({ hire, onClose, onDone }: { hire: any; onClose: () => void; onDone: () => void }) {
  const t = hire.contract.terms;
  const [busy, setBusy] = useState(false);
  const accept = async () => {
    setBusy(true);
    await api(`/v1/hires/${hire.id}/contract/accept`, { method: "POST" }).finally(() => setBusy(false));
    onDone();
  };
  return (
    <Modal open onClose={onClose} title="Contract" wide>
      <div className="kv">
        <div><span className="k">Brand</span><span>{t.parties.brand}</span></div>
        <div><span className="k">Creator</span><span>{t.parties.creator}</span></div>
        <div><span className="k">Deliverables</span><span>{t.deliverables}</span></div>
        <div><span className="k">Pay</span><span>{payLine({ pay_model: t.pay.model, cpm_paise: t.pay.cpm_paise, flat_paise: t.pay.flat_paise, cap_paise: t.pay.cap_paise_per_deliverable })}</span></div>
        <div><span className="k">Views counted for</span><span>{t.pay.tracking_days} days</span></div>
        <div><span className="k">Held in escrow</span><span>{inr(t.escrow.reserved_paise)} on Razorpay Route</span></div>
        <div><span className="k">Usage rights</span><span>{t.usage_rights}</span></div>
        <div><span className="k">Deadline</span><span>{t.deadline ? date(t.deadline) : "Open"}</span></div>
      </div>
      <div className="stack small">
        <p>{t.approval}</p><p>{t.disclosure}</p>{t.fee && <p>{t.fee}</p>}<p>{t.tax}</p><p>{t.disputes}</p>
        <p className="muted">Parties: {t.parties.intermediary}. Governing law: {t.governing_law}.</p>
      </div>
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button className="btn ghost" onClick={onClose}>Not now</button>
        <button className="btn primary" onClick={accept} disabled={busy}>{busy ? <Spinner /> : "Accept contract"}</button>
      </div>
    </Modal>
  );
}

function SubmitForm({ hire, onDone }: { hire: any; onDone: () => void }) {
  const { toast } = useSession();
  const b = hire.brief_full;
  const req = b.required_elements || {};
  const [url, setUrl] = useState("");
  const [hookId, setHookId] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  const { data: hooks } = useApi<any>(`/v1/creator/hooks?brief_id=${b.id}`);
  const caption = [`New favourite for this season.`, req.mention, ...(req.hashtags || []), req.discount_code ? `Code ${req.discount_code}` : ""]
    .filter(Boolean).join(" ");

  const simulate = async () => {
    try {
      const r = await api("/v1/dev/social/publish", { body: { platform: b.platforms[0], caption, quality: 1.2 } });
      setUrl(r.permalink);
      toast("Posted a test Reel on your simulated account");
    } catch (e: any) {
      toast(e.message, "error");
    }
  };
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await api(`/v1/hires/${hire.id}/deliverables`, { body: { post_url: url, hook_id: hookId || null } });
      toast("Submitted. Tracking starts now; the brand has 72 hours to approve.");
      setUrl("");
      onDone();
    } catch (e) {
      setErr(e as ApiError);
    } finally {
      setBusy(false);
    }
  };
  const checks = (err?.details as any)?.checks as Record<string, any> | undefined;
  return (
    <form className="card soft form" onSubmit={submit}>
      <div className="row between wrap-row">
        <h3 style={{ fontSize: 16, fontWeight: 600 }}>Submit your post</h3>
        <button type="button" className="btn sm" style={{ background: "var(--surface)" }} onClick={simulate}>
          <FlaskConical size={14} strokeWidth={S} /> Post a test Reel (simulator)
        </button>
      </div>
      <p className="muted small">Post from your connected account, then paste the link. We check it’s yours and that the caption has
        {req.mention ? ` ${req.mention},` : ""} {(req.hashtags || []).join(", ")}{req.discount_code ? `, ${req.discount_code}` : ""}.</p>
      <Field label="Post link" htmlFor={`url-${hire.id}`}>
        <input id={`url-${hire.id}`} className="input on-ground" placeholder="https://www.instagram.com/reel/…" value={url} onChange={(e) => setUrl(e.target.value)} />
      </Field>
      {hooks?.data?.length > 0 && (
        <Field label="Hook you used (optional)" hint="Lets your score learn which hook patterns work for you.">
          <select className="select" style={{ background: "var(--surface)" }} value={hookId} onChange={(e) => setHookId(e.target.value)}>
            <option value="">None</option>
            {hooks.data.map((h: any) => <option key={h.id} value={h.id}>{h.pattern}: {h.first_line}</option>)}
          </select>
        </Field>
      )}
      <ErrorNote error={err} />
      {checks && (
        <div className="items">
          {Object.entries(checks).map(([k, v]: any) => (
            <div key={k} className="item" style={{ background: "var(--surface)" }}><span className="grow">{k}</span>{v.ok === false ? <span className="tag bad">Missing</span> : v.ok ? <span className="tag good">Found</span> : <span className="tag">Brand checks</span>}</div>
          ))}
        </div>
      )}
      <button className="btn primary" disabled={busy || !url}>{busy ? <Spinner /> : <><Send size={15} strokeWidth={S} /> Submit for approval</>}</button>
    </form>
  );
}

function DisputeResponse({ d, onDone }: { d: any; onDone: () => void }) {
  const [text, setText] = useState("");
  const { toast } = useSession();
  if (!d.dispute || d.dispute.ops_decision || d.dispute.creator_response) return null;
  return (
    <form className="form" onSubmit={async (e) => {
      e.preventDefault();
      try { await api(`/v1/disputes/${d.dispute.id}/respond`, { body: { response: text } }); toast("Response sent to Flu ops"); onDone(); }
      catch (er: any) { toast(er.message, "error"); }
    }}>
      <Field label="Your response (within 48 hours)"><textarea className="textarea" value={text} onChange={(e) => setText(e.target.value)} placeholder="The refill is shown from 0:04 to 0:11…" /></Field>
      <button className="btn primary" disabled={text.trim().length < 5}>Send response</button>
    </form>
  );
}

export default function Work() {
  const [tab, setTab] = useState<"hires" | "apps">("hires");
  const hires = useApi<any>("/v1/creator/hires");
  const apps = useApi<any>("/v1/creator/applications");
  const [contract, setContract] = useState<any>(null);
  return (
    <>
      <div className="page-title"><div><h1>My work</h1><p>Contracts, posts in review, and what each one has earned.</p></div></div>
      <Tabs value={tab} onChange={setTab} items={[
        { id: "hires", label: "Hired", count: hires.data?.data.length },
        { id: "apps", label: "Applications", count: apps.data?.data.length },
      ]} />
      {tab === "hires" && (hires.loading && !hires.data ? <Loading /> : (
        hires.data?.data.length ? hires.data.data.map((h: any) => {
          const accepted = !!h.contract?.creator_accepted_at;
          const remaining = h.deliverables_expected - h.deliverables.length;
          return (
            <section key={h.id} className="card stack-lg fade-in">
              <div className="row between wrap-row">
                <div>
                  <div className="muted small">{h.brief.org.name}</div>
                  <h2 style={{ fontSize: 20, fontWeight: 600 }}>{h.brief.title}</h2>
                  <div className="muted small">{payLine(h.brief)} · {USAGE[h.brief_full.usage_rights]}{h.brief.deadline ? ` · Post by ${date(h.brief.deadline)}` : ""}</div>
                </div>
                <div className="row"><Status s={h.status} />{accepted ? <span className="tag good">Contract signed</span> : null}</div>
              </div>
              {!accepted && h.status === "active" && (
                <div className="note warn" style={{ alignItems: "center" }}>
                  <FileSignature size={16} strokeWidth={S} />
                  <span className="grow">Up to {inr((h.brief.pay_model === "flat" ? h.brief.flat_paise : Math.max(h.brief.cap_paise, h.brief.flat_paise)) * h.deliverables_expected)} is already held in escrow for you. Accept the contract to start posting.</span>
                  <button className="btn primary sm" onClick={() => setContract(h)}>Review contract</button>
                </div>
              )}
              {h.deliverables.map((d: any) => (
                <div key={d.id} className="stack">
                  <DeliverableCard d={d} />
                  <DisputeResponse d={d} onDone={hires.reload} />
                </div>
              ))}
              {accepted && remaining > 0 && h.status === "active" && <SubmitForm hire={h} onDone={hires.reload} />}
            </section>
          );
        }) : <div className="card"><Empty title="No hires yet">Apply to a few <Link href="/creator/briefs" className="link">open briefs</Link>. Brands see applicants ranked by Creator Score and niche fit.</Empty></div>
      ))}
      {tab === "apps" && (apps.loading && !apps.data ? <Loading /> : (
        <div className="card">
          {apps.data?.data.length ? (
            <div className="items">
              {apps.data.data.map((a: any) => (
                <Link key={a.id} href={`/creator/briefs/${a.brief.id}`} className="item link-row">
                  <div className="grow">
                    <div className="strong">{a.brief.title}</div>
                    <div className="muted small ellipsis">{a.brief.org.name} · “{a.pitch}”</div>
                  </div>
                  {a.invited && <span className="tag olive">Invited</span>}
                  <Status s={a.status} />
                </Link>
              ))}
            </div>
          ) : <Empty title="You haven’t applied to anything yet" />}
        </div>
      ))}
      {contract && <ContractModal hire={contract} onClose={() => setContract(null)} onDone={() => { setContract(null); hires.reload(); }} />}
    </>
  );
}
