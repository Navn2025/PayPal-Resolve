"use client";

import { useRef, useState, type FormEvent } from "react";
import { ArrowUpRight, Copy, Link2 } from "lucide-react";
import { type IntakeInvite, type Operations } from "@/lib/customer";
import { timeText, type CaseView, type LegacyCase, type Page, type Requester } from "@/lib/domain";
import { Button, Modal, Notice } from "./ui";

const explain = (failure: unknown) => failure instanceof Error ? failure.message : "Could not save. Try again.";

export function InviteForm({ onClose, request, demo }: { onClose: () => void; request: Requester; demo: boolean }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [invite, setInvite] = useState<IntakeInvite | null>(null);
  const [url, setUrl] = useState("");
  const linkInput = useRef<HTMLInputElement>(null);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const order = String(form.get("order")).trim();
    const email = String(form.get("email") ?? "").trim();
    setBusy(true); setError("");
    try {
      const issued = await request<IntakeInvite>("/resolution-cases/intake-invites", "POST", {
        order_reference: order,
        ...(email && { customer_email: email, send_email: form.has("send_email") }),
      });
      setUrl(issued.public_url ?? (window.location.origin + "/customer#" + issued.token));
      setInvite(issued);
    } catch (failure) { setError(explain(failure)); }
    finally { setBusy(false); }
  }
  return <Modal title="Invite customer" description="Create a private link that lets the buyer report one issue for a specific order." onClose={onClose} busy={busy}>
    {demo ? <div className="triage-form"><p className="muted">Try the form for a sample order. Connect your merchant account to invite a buyer.</p>
      <a href="/customer?intake=1" target="_blank" rel="noreferrer" className="button button-primary">Open sample intake <ArrowUpRight size={15} /></a></div>
      : invite ? <div className="customer-link-box">
        {invite.email_queued && <Notice tone="info">Invite email queued for delivery.</Notice>}
        <p>For order <strong>{invite.order_reference}</strong> · expires {timeText(invite.expires_at)}. Share the link privately with the buyer.</p>
        <label className="field"><span>Private intake link</span><input ref={linkInput} readOnly value={url} /></label>
        <div><Button onClick={async () => {
          try { await navigator.clipboard.writeText(url); setNotice("Link copied."); }
          catch { linkInput.current?.focus(); linkInput.current?.select(); setNotice("Copy the selected link to share it."); }
        }}><Copy size={15} /> Copy link</Button>
        <a className="button button-secondary" href={url} target="_blank" rel="noreferrer">Open intake <ArrowUpRight size={15} /></a></div>
        {notice && <Notice tone="success">{notice}</Notice>}
      </div> : <form className="triage-form" onSubmit={submit}>
        {error && <Notice>{error}</Notice>}
        <label className="field"><span>Order reference</span><input name="order" required maxLength={160} placeholder="e.g. ORD-4821" disabled={busy} /></label>
        <label className="field"><span>Buyer email (optional)</span><input name="email" type="email" maxLength={254} placeholder="buyer@example.com" disabled={busy} />
          <small>Use the email already verified for the order so the buyer can find the case after signing in.</small></label>
        <label className="customer-checkbox"><input type="checkbox" name="send_email" disabled={busy} /> Email this invite from Resolve</label>
        <Button type="submit" variant="primary" disabled={busy}><Link2 size={16} />{busy ? "Creating…" : "Create intake link"}</Button>
      </form>}
  </Modal>;
}

function localValue(value: string | null) {
  if (!value) return "";
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

export function PaymentLinkForm({ item, request, onClose, onSaved }: {
  item: CaseView; request: Requester; onClose: () => void; onSaved: () => void;
}) {
  const [payments, setPayments] = useState<LegacyCase[]>([]);
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function findPayments() {
    setBusy(true); setError("");
    try { setPayments((await request<Page<LegacyCase>>("/cases?limit=100")).items); setChecked(true); }
    catch (failure) { setError(explain(failure)); }
    finally { setBusy(false); }
  }
  async function link(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    const id = String(values.get("payment") || values.get("manual") || "").trim();
    if (!id) { setError("Select a payment case or enter its ID."); return; }
    setBusy(true); setError("");
    try { await request("/resolution-cases/" + item.id + "/payment-link", "PUT", { refund_case_id: id }); onSaved(); }
    catch (failure) { setError(explain(failure)); }
    finally { setBusy(false); }
  }
  return <Modal title="Link payment record" description="Attach the existing payment for this issue so the case can track an agreed refund." onClose={onClose} busy={busy}>
    <form className="triage-form" onSubmit={link}>
      {error && <Notice>{error}</Notice>}
      <p className="muted">Case order reference: <strong>{item.order_reference ?? "Not recorded"}</strong></p>
      {!checked && <Button onClick={findPayments} disabled={busy}>Load payment records</Button>}
      {checked && <label className="field"><span>Existing payment case</span><select name="payment" defaultValue="">
        <option value="">{payments.length ? "Select a case" : "No payment records found"}</option>
        {payments.map((payment) => <option key={payment.id} value={payment.id}>{payment.order_id} · {payment.complaint}</option>)}
      </select></label>}
      <label className="field"><span>Payment case ID</span><input name="manual" placeholder="Resolve payment case ID" /></label>
      <label className="customer-checkbox"><input type="checkbox" required /> I checked that this payment belongs to the order in this case.</label>
      <Button type="submit" variant="primary" disabled={busy}><Link2 size={16} /> Link payment</Button>
    </form>
  </Modal>;
}

export function OperationsForm({ current, onClose, onSave }: {
  current: Operations; onClose: () => void; onSave: (data: object) => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    const date = String(values.get("due_at") ?? "");
    setBusy(true); setError("");
    try { await onSave({ expected_revision: current.revision, assignee: String(values.get("assignee") ?? "").trim() || null,
      due_at: date ? new Date(date).toISOString() : null, waiting_on_customer: values.has("waiting") }); }
    catch (failure) { setError(explain(failure)); }
    finally { setBusy(false); }
  }
  return <Modal title="Manage case" description="Set who owns this case and when the next update is due." onClose={onClose} busy={busy}>
    <form className="triage-form" onSubmit={submit}>
      {error && <Notice>{error}</Notice>}
      <label className="field"><span>Assignee</span><input name="assignee" defaultValue={current.assignee ?? ""} maxLength={80} placeholder="Name or team" /></label>
      <label className="field"><span>Case due date</span><input name="due_at" type="datetime-local" defaultValue={localValue(current.due_at)} />
        {current.promise_due_at && <small>If left blank, the case uses the promise deadline: {timeText(current.promise_due_at)}.</small>}</label>
      <label className="customer-checkbox"><input name="waiting" type="checkbox" defaultChecked={current.waiting_on_customer} /> Waiting on customer</label>
      <p className="muted">A new customer reply clears this setting. The next step and deadline appear in the customer portal.</p>
      <Button type="submit" variant="primary" disabled={busy}>{busy ? "Saving…" : "Save case settings"}</Button>
    </form>
  </Modal>;
}
