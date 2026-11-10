"use client";
import { useRef, useState, type FormEvent } from "react";
import { failureText, type ReturnCatalog, type ReturnRecord } from "@/lib/platform";
import { Button, Notice } from "./ui";
import { type PromiseView } from "@/lib/domain";

export interface PublicReturnPolicy {policy_enabled:boolean;revision:number;window_days:number|null;shipping_paid_by:string|null;restocking_fee:string|null;currency:string;inspection_required:boolean;evidence_required:boolean;instructions:string}

export function ReturnRequestForm({ catalog, submit, done, policy }: { policy?:PublicReturnPolicy; catalog: ReturnCatalog; submit: (body: object) => Promise<unknown>; done: () => void }) {
  const [orderId, setOrderId] = useState(catalog.orders[0]?.id ?? "");
  const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  const requestId = useRef("");
  const order = catalog.orders.find(item => item.id === orderId);
  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    const form = event.currentTarget;
    const data = new FormData(form);
    const items = order?.items.map(i => ({ product_id: i.product_id, quantity: Number(data.get(i.product_id) ?? 0) })).filter(i => i.quantity > 0) ?? [];
    if (!requestId.current) requestId.current = crypto.randomUUID();
    try {
      if (!items.length) throw new Error("Select at least one item to return.");
      await submit({ request_id: requestId.current, order_id: orderId, items, reason: String(data.get("reason") ?? "") });
      requestId.current = ""; form.reset(); done();
    } catch (failure) { setError(failureText(failure)); } finally { setBusy(false); }
  }
  if (!catalog.orders.length) return <p className="muted">A merchant must connect this case to an order before items can be selected.</p>;
  if (catalog.orders.every(o => o.items.every(i => i.available_quantity === 0))) return <p>All items on these orders already have return requests.</p>;
  return <form className="ops-form" onSubmit={send}>
    {error && <Notice>{error}</Notice>}
    {policy?.policy_enabled ? <div role="note"><p>Return window: {policy.window_days} days after delivery. Return shipping paid by {policy.shipping_paid_by}. Merchant-stated restocking fee: {policy.currency} {policy.restocking_fee}.</p><p>{policy.instructions}</p>{policy.inspection_required&&<p>Item and quantity inspection is required.</p>}{policy.evidence_required&&<p>Add item evidence to your case for merchant review.</p>}<p>Submitting a request does not approve a return or refund. Wait for the merchant’s instructions before shipping.</p></div> : <p>The merchant will confirm eligibility, shipping costs and any applicable fees before you ship.</p>}
    <label>Order<select value={orderId} onChange={e => { setOrderId(e.target.value); requestId.current = ""; }}>{catalog.orders.map(o => <option key={o.id} value={o.id}>{o.order_reference}</option>)}</select></label>
    {order?.items.map(i => <label key={i.product_id}>{i.name ?? i.product_id} <small>{i.available_quantity} available to return</small><input aria-label={`Return quantity for ${i.name ?? i.product_id}`} type="number" name={i.product_id} min={0} max={i.available_quantity} defaultValue={0} step={1} /></label>)}
    <label>Reason<textarea name="reason" maxLength={2000} required /></label>
    <Button type="submit" disabled={busy}>{busy ? "Submitting…" : "Request return"}</Button>
  </form>;
}

export function ReturnProgress({ item, update, promises = [] }: { item: ReturnRecord; update?: (body: object) => Promise<void>; promises?: PromiseView[] }) {
  const [action, setAction] = useState(""); const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  const actions: Record<string, [string, string][]> = {
    requested: [["approve", "Approve return"], ["reject", "Decline return"]], approved: [["ship_return", "Record return shipment"]],
    in_transit: [["receive", "Confirm warehouse receipt"]], received: [["pass_inspection", "Confirm inspection passed"]],
    inspection_passed: [["ship_replacement", "Record replacement shipment"], ["complete", "Complete return without replacement"]], replacement_shipped: [["complete", "Complete workflow"]],
  };
  const choices = actions[item.status] ?? [];
  const selected = choices.some(c => c[0] === action) ? action : choices[0]?.[0] ?? "";
  const milestone = selected === "receive" ? "warehouse_received" : selected === "pass_inspection" ? "inspection_passed" : null;
  const matchingPromises = promises.filter(p => p.terms.target.kind === "return" && p.terms.target.milestone === milestone);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!update) return;
    const values = new FormData(event.currentTarget); setBusy(true); setError("");
    const shipment = ["ship_return", "ship_replacement"].includes(selected) ? { carrier: String(values.get("carrier")), tracking_code: String(values.get("tracking_code")), reference: String(values.get("reference")) } : undefined;
    const linked = matchingPromises.find(p => p.id === values.get("promise_id"));
    try { await update({ expected_revision: item.revision, action: selected, note: String(values.get("note")), ...(shipment && { shipment }), ...(linked && { promise_id: linked.id, promise_revision: linked.revision }) }); }
    catch (failure) { setError(failureText(failure)); } finally { setBusy(false); }
  }
  return <article className="ops-record"><strong>Return · {item.status.replaceAll("_", " ")}</strong><p>{item.reason}</p>
    <small>Merchant-recorded fulfillment progress</small>
    <p>{item.items.map(i => `${i.product_id} × ${i.quantity}`).join(", ")}</p>
    {item.tracking && <p>Return: {item.tracking.carrier} · {item.tracking.tracking_code}</p>}
    {item.replacement && <p>Replacement: {item.replacement.carrier} · {item.replacement.tracking_code}</p>}
    {update && choices.length > 0 && <form className="ops-form" onSubmit={submit}>
      {error && <Notice>{error}</Notice>}<label>Next step<select value={selected} onChange={e => setAction(e.target.value)}>{choices.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>
      {["ship_return", "ship_replacement"].includes(selected) && <><label>Carrier<input name="carrier" required maxLength={60} /></label><label>Tracking code<input name="tracking_code" required maxLength={100} /></label><label>Shipment reference<input name="reference" required maxLength={160} /></label></>}
      {matchingPromises.length > 0 && <label>Confirm a matching promise milestone<select name="promise_id" defaultValue=""><option value="">Record this return step only</option>{matchingPromises.map(p => <option key={p.id} value={p.id}>{p.terms.promise}</option>)}</select></label>}
      <label>Evidence or note<textarea name="note" required maxLength={2000} /></label><Button type="submit" disabled={busy}>{busy ? "Saving…" : "Record this step"}</Button>
    </form>}
  </article>;
}
