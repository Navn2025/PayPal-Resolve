"use client";

import { useState, type FormEvent } from "react";
import { Check, Download, FileText, Paperclip, Send } from "lucide-react";
import { issueLabels, type CustomerMilestone, type CustomerNextStep, type Evidence } from "@/lib/customer";
import { timeText } from "@/lib/domain";
import { Button, Notice } from "./ui";

const message = (error: unknown) => error instanceof Error ? error.message : "This action could not be completed.";

export function IntakeForm({ order, onSubmit }: { order: string; onSubmit: (issueType: string, description: string) => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setBusy(true); setError("");
    try { await onSubmit(String(data.get("issue")), String(data.get("description")).trim()); }
    catch (failure) { setError(message(failure)); }
    finally { setBusy(false); }
  }
  return <section className="section-card customer-intake">
    <div className="eyebrow">ORDER SUPPORT</div><h1>Request help with your order</h1><p>Order <strong>{order}</strong></p>
    <form onSubmit={submit}>
      {error && <Notice>{error}</Notice>}
      <label className="field"><span>What happened?</span><select name="issue" defaultValue="" required>
        <option value="" disabled>Select an issue</option>
        {Object.entries(issueLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
      </select></label>
      <label className="field"><span>Describe the issue</span><textarea name="description" rows={5} maxLength={2000} required
        placeholder="Tell the merchant what happened. You can attach evidence after submitting." /></label>
      <Button type="submit" variant="primary" disabled={busy}><Send size={16} />{busy ? "Submitting…" : "Submit support request"}</Button>
    </form>
  </section>;
}

export function EvidencePanel({ files, onUpload, onDownload }: {
  files: Evidence[]; onUpload?: (file: File) => Promise<void>; onDownload: (file: Evidence) => Promise<void>;
}) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const file = new FormData(form).get("evidence");
    if (!(file instanceof File) || !file.size || !onUpload) return;
    setError(""); setBusy(true);
    try {
      if (file.size > 2 * 1024 * 1024) throw new Error("Choose a file up to 2 MiB.");
      await onUpload(file); form.reset();
    } catch (failure) { setError(message(failure)); } finally { setBusy(false); }
  }
  return <section className="section-card customer-evidence-panel customer-print-hide">
    <div className="section-head"><div><div className="eyebrow">SUPPORTING DOCUMENTS</div><h3>Customer evidence</h3></div><Paperclip size={17} /></div>
    {error && <Notice>{error}</Notice>}
    {!files.length && <p className="muted">No customer evidence attached yet.</p>}
    <ul className="evidence-files">{files.map((file) => <li key={file.id}><FileText size={16} />
      <div><strong>{file.filename}</strong><small>Customer submitted · {Math.max(1, Math.ceil(file.size_bytes / 1024))} KB</small></div>
      <Button className="small-button" onClick={() => {
        setError(""); void onDownload(file).catch((failure) => setError(message(failure)));
      }} aria-label={`Download ${file.filename}`}><Download size={15} /> Download</Button></li>)}</ul>
    {onUpload && <form className="evidence-upload" onSubmit={upload}>
      <label className="field"><span>Attach evidence</span><input name="evidence" type="file" accept=".pdf,.png,.jpg,.jpeg" required disabled={busy} />
        <small>PDF, PNG or JPEG · up to 2 MiB each</small></label>
      <Button type="submit" disabled={busy}><Paperclip size={15} /> {busy ? "Uploading…" : "Upload evidence"}</Button>
    </form>}
  </section>;
}

const milestoneLabels: Record<CustomerMilestone["source"], string> = {
  customer_submitted: "Customer submitted", merchant_recorded: "Merchant recorded",
  provider_confirmed: "Provider confirmed", resolve: "Resolve",
};

export function CustomerTimeline({ milestones, next }: { milestones: CustomerMilestone[]; next: CustomerNextStep }) {
  const actors = { customer: "Your turn", merchant: "Waiting on merchant", paypal: "Waiting on PayPal", none: "No action needed" };
  return <section className="section-card customer-timeline">
    <div className="section-head"><div><div className="eyebrow">CASE PROGRESS</div><h3>Status timeline</h3></div></div>
    <div className="customer-next"><strong>{actors[next.actor]}</strong><p>{next.action}</p>
      {next.due_at && <small className={next.overdue ? "overdue" : ""}>{next.overdue ? "Overdue · " : "Due "}{timeText(next.due_at)}</small>}</div>
    <ol className="event-list">{milestones.map((event, index) => <li key={index}>
      <span className={`event-icon ${event.source === "provider_confirmed" ? "event-provider" : ""}`}><Check size={15} /></span>
      <div><div className="event-title"><strong>{event.label}</strong><time dateTime={event.occurred_at}>{timeText(event.occurred_at)}</time></div>
        <small>{milestoneLabels[event.source]}</small></div>
    </li>)}</ol>
  </section>;
}
