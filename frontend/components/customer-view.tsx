"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowUpRight, CheckCircle2, ClipboardCheck, Clock3, LockKeyhole, Printer, RefreshCw, ShieldCheck } from "lucide-react";
import { ApiError, dateText, money, remedyLabels, uuid } from "@/lib/domain";
import { customerLabels, customerRequest, demoCustomer, downloadFile, issueLabels, saveBlob, uploadCustomerFile, type CustomerCase, type Evidence, type IntakeView, type Message } from "@/lib/customer";
import { Badge, Brand, Button, Empty, Notice, remedyIcons } from "./ui";
import { Conversation } from "./conversation";
import { CustomerTimeline, EvidencePanel, IntakeForm } from "./customer-actions";

const noLink = "Open the private link your merchant shared with you.";
const invalidLink = "This customer link is invalid, expired, or revoked.";

export function CustomerView() {
  const [item, setItem] = useState<CustomerCase | null>(null);
  const [demo, setDemo] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [started, setStarted] = useState(false);
  const [intake, setIntake] = useState<string | null>(null);
  const token = useRef("");
  const version = useRef(0);
  const demoFiles = useRef(new Map<string, File>());

  async function load(value: string) {
    const seq = ++version.current;
    setLoading(true); setError("");
    try {
      if (value.startsWith("rint_")) {
        const invite = await customerRequest<IntakeView>("intake-view", value);
        if (seq !== version.current) return;
        if (!invite.submitted) { setIntake(invite.order_reference); return; }
      }
      const current = await customerRequest<CustomerCase>("view", value);
      if (seq === version.current) { setIntake(null); setItem(current); }
    } catch (failure) {
      if (seq !== version.current) return;
      if (failure instanceof ApiError && failure.status === 404) { setItem(null); setIntake(null); }
      setError(failure instanceof Error ? failure.message : "Could not load the case.");
    } finally { if (seq === version.current) setLoading(false); }
  }
  useEffect(() => {
    function open() {
      token.current = window.location.hash.slice(1);
      const params = new URLSearchParams(window.location.search);
      const sampleIntake = !token.current && params.get("intake") === "1";
      const sample = !token.current && params.get("demo") === "1";
      version.current += 1;
      setItem(sample ? structuredClone(demoCustomer) : null); setDemo(sample || sampleIntake); setError(""); setStarted(true);
      setIntake(sampleIntake ? "ORD-DEMO-4821" : null);
      if (sample || sampleIntake || !token.current) setLoading(false);
      else if (!/^(rsvp|rint|racp)_[A-Za-z0-9_-]{43}$/.test(token.current)) { setError(invalidLink); setLoading(false); }
      else void load(token.current);
    }
    open();
    window.addEventListener("hashchange", open);
    return () => { version.current += 1; window.removeEventListener("hashchange", open); };
  }, []);

  const refresh = () => { if (!demo && token.current) void load(token.current); };
  async function send(body: string, requestId: string) {
    const currentToken = token.current;
    const message: Message = demo
      ? { id: uuid(), body, sender: "customer", created_at: new Date().toISOString() }
      : await customerRequest<Message>("messages", currentToken, { body, request_id: requestId }).catch((failure) => {
        if (failure instanceof ApiError && failure.status === 404 && token.current === currentToken) { setItem(null); setError(invalidLink); }
        throw failure;
      });
    if (token.current === currentToken) {
      setItem((previous) => previous && !previous.messages.some((entry) => entry.id === message.id)
        ? { ...previous, messages: [...previous.messages, message] } : previous);
      if (!demo) void load(currentToken);
    }
  }
  async function submitIntake(issue: string, description: string) {
    if (!intake) return;
    const currentToken = token.current;
    const timestamp = new Date().toISOString();
    const result = demo ? {
      ...structuredClone(demoCustomer), title: issueLabels[issue], order_reference: intake, promises: [], refund: null,
      messages: [{ id: uuid(), sender: "customer" as const, body: description, created_at: timestamp }],
      timeline: [{ label: "Request received", source: "customer_submitted" as const, occurred_at: timestamp }],
      next_step: { actor: "merchant" as const, action: "The merchant will review your request.", due_at: null, overdue: false },
    } : await customerRequest<CustomerCase>("intake", currentToken, { issue_type: issue, description });
    if (token.current === currentToken) { setItem(result); setIntake(null); }
  }
  async function upload(file: File) {
    const currentToken = token.current;
    const entry: Evidence = demo ? {
      id: uuid(), filename: file.name, content_type: file.type, size_bytes: file.size, created_at: new Date().toISOString(), source: "customer_submitted",
    } : await uploadCustomerFile(currentToken, file);
    if (demo) demoFiles.current.set(entry.id, file);
    if (token.current === currentToken) setItem((previous) => previous && !previous.evidence.some((item) => item.id === entry.id)
      ? { ...previous, evidence: [...previous.evidence, entry] } : previous);
  }

  return <div className="customer-shell">
    <header className="customer-top customer-print-hide"><div><Link href="/" className="site-brand" aria-label="Resolve home"><Brand small /></Link><span>Customer portal</span></div>
      <div className="customer-account-nav"><a href="/customer/account">My cases</a><span className="provider-chip"><LockKeyhole size={13} /> {demo ? "Sample case" : "Private case access"}</span></div></header>
    <main className="customer-main">
      {intake ? <IntakeForm order={intake} onSubmit={submitIntake} /> : !item ? <section className="section-card customer-welcome">
        <div className="eyebrow">CASE STATUS</div><h1>Track your resolution</h1>
        {error && <Notice>{error}</Notice>}
        <Empty title={loading || !started ? "Opening customer portal…" : error ? "Case link unavailable" : "Have a private link?"}
          detail={loading ? "Checking access to your case." : error ? "Ask the merchant for a new link if you need access." : noLink}
          action={!loading && !error ? <a className="button button-secondary" href="/customer?demo=1">View a sample case <ArrowUpRight size={15} /></a> : undefined} />
      </section> : <>
        <section className="customer-hero">
          <div className="customer-hero-text"><div className="eyebrow">YOUR CASE</div><h1>{item.title}</h1>
            <p>{item.order_reference ? `Order ${item.order_reference}` : "Your agreed remedy and the latest confirmed progress."}</p></div>
          <Badge outcome={item.outcome} label={customerLabels[item.outcome]} />
        </section>
        {error && <Notice>{error}</Notice>}
        {demo && <Notice tone="info">This is a sample. Messages stay in this demo and no money moves.</Notice>}
        <section className="section-card customer-status">
          <div className="section-head"><div><div className="eyebrow">RESOLUTION SUMMARY</div><h3>What happens next</h3></div>
            <div className="customer-summary-actions customer-print-hide">
              {!demo && <Button className="small-button" onClick={refresh} disabled={loading}><RefreshCw size={15} className={loading ? "spin" : ""} /> Refresh status</Button>}
              <Button className="small-button" onClick={() => window.print()}><Printer size={15} /> Print summary</Button>
            </div></div>
          {item.refund && <>
            <div className="money-grid">
              <div className="money-stat"><div className="money-caption"><ClipboardCheck size={15} /> Agreed refund</div><strong>{money(item.refund.promised_amount)}</strong></div>
              <div className="money-stat money-confirmed"><div className="money-caption"><ShieldCheck size={15} /> {demo ? "Confirmed in demo" : "Confirmed by PayPal"}</div><strong>{money(item.refund.confirmed_amount)}</strong></div>
              <div className="money-stat money-outstanding"><div className="money-caption"><Clock3 size={15} /> Still owed</div><strong>{money(item.refund.outstanding_amount)}</strong></div>
            </div>
            <p className="customer-refund-note">{demo ? "Simulated refund progress" : "PayPal Sandbox refund progress"}{Number(item.refund.pending_amount) > 0 ? ` · ${money(item.refund.pending_amount)} awaiting confirmation` : ""}.</p>
          </>}
          <ul className="customer-promises" aria-label="Agreed remedies">{item.promises.map((promise, index) => {
            const Icon = remedyIcons[promise.kind];
            return <li key={index}><span className="promise-icon"><Icon size={18} /></span><div>
              <strong>{remedyLabels[promise.kind]}</strong><p>{promise.promise}</p>
              {promise.provider_confirmed && <small><CheckCircle2 size={13} /> Provider confirmed</small>}
              {promise.due_at && <small>Due {dateText(promise.due_at)}</small>}
            </div><Badge outcome={promise.outcome} label={customerLabels[promise.outcome]} /></li>;
          })}</ul>
          {!item.promises.length && <p className="muted">The merchant has not recorded an agreed remedy yet.</p>}
        </section>
        <CustomerTimeline milestones={item.timeline} next={item.next_step} />
        <EvidencePanel files={item.evidence} onUpload={upload} onDownload={async (file) => {
          if (demo) { const blob = demoFiles.current.get(file.id); if (blob) saveBlob(blob, file.filename); }
          else await downloadFile("/api/customer-portal/evidence/" + file.id, file.filename, token.current);
        }} />
        <Conversation messages={item.messages} viewer="customer" onSend={send} onRefresh={demo ? undefined : refresh} refreshing={loading} />
        {!demo && <p className="customer-foot customer-print-hide"><LockKeyhole size={14} /> This link expires {dateText(item.expires_at)}. Keep it private.</p>}
      </>}
    </main>
  </div>;
}
