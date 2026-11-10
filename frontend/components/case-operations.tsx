"use client";
import { MerchantAssurance, ReturnGuidePanel } from "./assurance";
import { useEffect, useState, type FormEvent } from "react";
import { platform, failureText, type ReturnCatalog } from "@/lib/platform";
import { type PromiseView } from "@/lib/domain";
import { readJson } from "@/lib/http";
import { Button, Notice } from "./ui";
import { DeferredDetails } from "./deferred-details";
import { ReturnProgress, ReturnRequestForm } from "./return-workflow";

interface AppRequest { issue_id: string; source: string; reason: string; requested_resolution: string; message: string; created_at: string }
interface Offer { id: string; revision: number; status: string; expires_at: string; choices: { id: string; promise: string }[]; selected_choice: string | null; decision_at: string | null }
interface Package { id: string; dispute_id: string; reason: string; snapshot_hash: string; reviewed_at: string | null; created_at: string }

export function CaseOperationsPanel({ caseId, promises, role }: { caseId: string; promises: PromiseView[]; role:string }) {
  const [requests, setRequests] = useState<AppRequest[]>([]);
  const [offers, setOffers] = useState<Offer[]>([]); const [catalog, setCatalog] = useState<ReturnCatalog | null>(null);
  const [packages, setPackages] = useState<Package[]>([]); const [preview, setPreview] = useState<unknown>(null);
  const [opened, setOpened] = useState<string[]>([]); const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  const base = `cases/${caseId}`;
  async function load(sections = [...opened, "support"]) {
    await Promise.all([
      ...(sections.includes("offers") ? [platform<{items:Offer[]}>(base+"/offers").then(p=>setOffers(p.items))] : []),
      ...(sections.includes("returns") ? [platform<ReturnCatalog>(base+"/returns").then(setCatalog)] : []),
      ...(sections.includes("packages") ? [platform<{items:Package[]}>(base+"/dispute-packages").then(p=>setPackages(p.items))] : []),
      ...(sections.includes("support") ? [platform<{items:AppRequest[]}>(base+"/support-requests").then(p=>setRequests(p.items))] : []),
    ]);
  }
  function open(section:string) {
    setOpened(previous=>previous.includes(section)?previous:[...previous,section]);
    void load([section]).catch(f=>setError(failureText(f)));
  }
  useEffect(() => { void load(["support"]).catch(f=>setError(failureText(f))); }, [caseId]);
  async function act(action: () => Promise<unknown>) { setBusy(true); setError(""); try { await action(); await load(); } catch (f) { setError(failureText(f)); } finally { setBusy(false); } }
  async function publish(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const data = new FormData(event.currentTarget);
    const selected = data.getAll("promise").map(String);
    await act(async () => {
      if (!selected.length) throw new Error("Select at least one remedy option.");
      return platform(base + "/offers", "POST", { choices: selected.map(id => ({ promise_id: id, expected_revision: promises.find(p => p.id === id)!.revision })), expires_at: new Date(String(data.get("expiry"))).toISOString() });
    });
  }
  async function download(id: string) {
    const response = await fetch(`/api/platform/${base}/dispute-packages/${id}/export`);
    if (!response.ok) { await readJson(response); return; }
    const url = URL.createObjectURL(await response.blob()); const a = document.createElement("a"); a.href = url; a.download = `resolve-dispute-${id}.json`; a.click(); URL.revokeObjectURL(url);
  }
  const write = role !== "viewer";
  return <section className="section-card case-operations-panel"><div className="eyebrow">RESOLUTION WORKFLOW</div><h2>Offers, returns and dispute evidence</h2>
    {error && <Notice>{error}</Notice>}
    <MerchantAssurance caseId={caseId} role={role}/>
    {requests.length > 0 && <section><h3>Customer requests from connected apps</h3><p>Requested remedies need merchant review before they become promises.</p>{requests.map(item => <article className="ops-record" key={item.issue_id}><strong>{item.reason.replaceAll("_", " ")}</strong><p>{item.message}</p><p>Customer prefers: <strong>{item.requested_resolution}</strong> · {item.source}</p><small>{new Date(item.created_at).toLocaleString()}</small></article>)}</section>}

    <DeferredDetails title="Buyer resolution offers" onOpen={()=>open("offers")}><p>Publish exact promise versions for the buyer to accept. A refund offer adds an acceptance requirement; financial approval and submission remain separate.</p>
      {write && promises.length > 0 && <form className="ops-form" onSubmit={publish}><fieldset disabled={busy}><legend>Available choices (up to four)</legend>{promises.map(p => <label className="ops-check" key={p.id}><input type="checkbox" name="promise" value={p.id} />{p.terms.promise}</label>)}</fieldset><label>Offer expires<input type="datetime-local" name="expiry" required /></label><Button type="submit" disabled={busy}>Publish buyer offer</Button></form>}
      {!promises.length && <p>Record a promise before publishing an offer.</p>}
      {offers.map(o => <article className="ops-record" key={o.id}><strong>Offer {o.revision} · {o.status}</strong><p>Expires {new Date(o.expires_at).toLocaleString()}</p>{o.choices.map(c => <p key={c.id}>{c.promise}{o.selected_choice === c.id ? " · Buyer accepted" : ""}</p>)}{o.decision_at && <small>Decision recorded {new Date(o.decision_at).toLocaleString()}</small>}</article>)}
    </DeferredDetails>
    <DeferredDetails title="Guided returns and replacements" onOpen={()=>open("returns")}><p>Keep shipment, warehouse receipt and inspection as separate steps. Shipment references record fulfillment arranged by the merchant.</p>
      {catalog && <>{catalog.items.map(item => <div key={item.id}><ReturnProgress item={item} promises={promises} update={write ? async body => { await platform(`${base}/returns/${item.id}`, "PUT", body); await load(); } : undefined}/><ReturnGuidePanel item={item} caseId={caseId} role={role}/></div>)}{write && <ReturnRequestForm catalog={catalog} submit={body => platform(base + "/returns", "POST", body)} done={() => void load().catch(f => setError(failureText(f)))} />}</>}
    </DeferredDetails>
    <DeferredDetails title="Dispute evidence packages" onOpen={()=>open("packages")}><p>Prepare a private snapshot with source labels and a missing-evidence checklist. Review before exporting. This does not submit evidence to PayPal.</p>
      {write && <form className="ops-form" onSubmit={e => { e.preventDefault(); const values = new FormData(e.currentTarget); void act(() => platform(base + "/dispute-packages", "POST", { dispute_id: values.get("dispute"), reason: values.get("reason") })); }}>
        <label>PayPal dispute reference<input name="dispute" required pattern="[A-Za-z0-9_-]+" maxLength={80} /></label><label>Dispute reason<select name="reason"><option value="item_not_received">Item not received</option><option value="not_as_described">Item not as described</option><option value="unauthorized">Unauthorized payment</option><option value="credit_not_processed">Credit not processed</option><option value="duplicate_charge">Duplicate charge</option><option value="canceled_recurring">Canceled recurring payment</option><option value="other">Other</option></select></label><Button type="submit" disabled={busy}>Prepare evidence package</Button>
      </form>}
      {packages.map(p => <article className="ops-record" key={p.id}><strong>{p.dispute_id} · {p.reason.replaceAll("_", " ")}</strong><p>{p.reviewed_at ? "Reviewed" : "Awaiting merchant review"} · {new Date(p.created_at).toLocaleString()}</p><small className="ops-hash">Snapshot: {p.snapshot_hash}</small><div className="ops-actions">
        <Button disabled={busy} onClick={() => void act(async () => setPreview(await platform(`${base}/dispute-packages/${p.id}`)))}>Inspect snapshot</Button>
        {["owner", "manager"].includes(role) && !p.reviewed_at && <Button disabled={busy} onClick={() => void act(() => platform(`${base}/dispute-packages/${p.id}/review`, "POST"))}>Record review</Button>}
        {p.reviewed_at && <Button disabled={busy} onClick={() => void act(() => download(p.id))}>Export JSON</Button>}
      </div></article>)}
      {preview !== null && <div className="ops-record"><Button onClick={() => setPreview(null)}>Close snapshot</Button><pre className="ops-snapshot">{JSON.stringify(preview, null, 2)}</pre></div>}
    </DeferredDetails>
  </section>;
}
