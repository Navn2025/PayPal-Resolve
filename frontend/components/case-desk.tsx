"use client";

import { ArrowDownToLine, ArrowLeft, ArrowLeftRight, ArrowRight, ArrowUpRight, CalendarDays, Check, ChevronDown, ClipboardCheck, Clock3, FileText, Fingerprint, ListChecks, PackageCheck, Plus, Printer, RefreshCw, ShieldCheck, Wallet, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { dateText, money, outcomeLabels, pretty, remedyLabels, shortId, sourceLabels, timeText, type Approval, type CaseView, type Execution, type PromiseView, type Reconciliation, type Requester, type Timeline } from "@/lib/domain";
import { Badge, Brand, Button, Empty, Notice, remedyIcons } from "./ui";
import { MerchantCustomer } from "./merchant-customer";
import { workflowLabels, type Operations } from "@/lib/customer";
import { HelpdeskPanel } from "./helpdesk-panel";

export type DeskTab = "overview" | "timeline" | "receipt" | "customer";
export interface PaymentActions {
  basis: Reconciliation | null;
  approval?: Approval;
  execution?: Execution;
  nextMessage: string;
  canReview: boolean;
  canSubmit: boolean;
  busy: boolean;
  error?: string;
  onReview: () => void;
  onSubmit: () => void;
  onRefresh: () => void;
  onCheckExecution: () => void;
  onSimulateOutside?: () => void;
}

interface DeskProps {
  item: CaseView; tab: DeskTab; setTab: (tab: DeskTab) => void; demo: boolean;
  request: Requester;
  timeline: Timeline | null; timelineError?: string; loadMore: () => void; loadingTimeline: boolean;
  payment: PaymentActions; onAdd: () => void; onEdit: (p: PromiseView) => void;
  onEvidence: (p: PromiseView) => void; onRefresh: (p: PromiseView) => void; onExport: () => void;
  onBack: () => void; refreshing: string | null; error?: string; verifiedMessage?: string;
  onManage: () => void; onLinkPayment: () => void; onOperations: (id: string, operations: Operations) => void;
  /** Merchant-only AI and check panels, shown in the overview's promises area. */
  assistant?: ReactNode;
}

function Metric({ label, value, style, Icon }: { label: string; value: string; style: string; Icon: LucideIcon }) {
  return <div className={`money-stat money-${style}`}><div className="money-caption"><Icon size={15} /><span>{label}</span></div><strong>{value}</strong></div>;
}

function PaymentPanel({ item, payment, demo, onAdd }: Pick<DeskProps, "item" | "payment" | "demo" | "onAdd">) {
  const refund = item.promises.find((p) => p.terms.target.kind === "refund");
  const progress = refund?.refund_progress;
  if (!progress) {
    if (!item.refund_case_id || refund) return null;
    return <div className="section-card linked-panel"><span className="section-icon"><Wallet size={19} /></span><div><strong>Payment record linked</strong>
      <p>Record a refund promise to see how much was returned and what still needs to happen.</p></div>
      <Button onClick={onAdd}><Plus size={16} /> Record promise</Button></div>;
  }
  const total = Number(progress.promised_amount);
  const paid = Number(progress.provider_completed_amount);
  const percent = total > 0 ? Math.min(100, Math.round((paid / total) * 100)) : 0;
  const done = refund.outcome === "fulfilled";
  const needsReview = refund.outcome === "needs_review";
  const execution = payment.execution;
  return <>
    <section className="section-card refund-card" aria-labelledby="refund-title">
      <div className="section-head refund-head"><div><div className="eyebrow">PAYMENT RESOLUTION</div><h3 id="refund-title">Refund reconciliation</h3></div>
        <span className="provider-chip"><span className="paypal-mark" aria-hidden="true">P</span> PayPal {demo ? "· Demo" : "Sandbox"}</span></div>
      <div className="money-grid">
        <Metric label="Promised" value={money(progress.promised_amount)} style="promise" Icon={ClipboardCheck} />
        <Metric label={demo ? "Confirmed in demo" : "PayPal confirmed"} value={money(progress.provider_completed_amount)} style="confirmed" Icon={ShieldCheck} />
        <Metric label="Still owed" value={money(progress.outstanding_amount)} style="outstanding" Icon={Wallet} />
      </div>
      <div className="progress-row"><div className="progress-label"><span>Refund progress</span><strong>{percent}%</strong></div>
        <div className="progress-track" role="progressbar" aria-label="Refund progress" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}>
          <span style={{ width: percent + "%" }} /></div></div>
      <div className="proof-foot"><span><Clock3 size={14} /> {demo ? "Simulated evidence" : refund.checked_at ? `Checked ${timeText(refund.checked_at)}` : "No PayPal check yet"}</span>
        <span>{Number(progress.provider_pending_amount) > 0 ? `${money(progress.provider_pending_amount)} pending` : progress.history_current ? "History current" : "Refresh history for current balance"}</span></div>
    </section>
    <section className={`action-card ${done ? "action-done" : ""}`} aria-label="Next refund action">
      <div className="action-symbol">{done ? <Check size={22} /> : <ShieldCheck size={22} />}</div>
      <div className="action-copy"><div className="eyebrow">{done ? "VERIFIED OUTCOME" : payment.approval ? "APPROVAL RECORDED" : "NEXT ACTION"}</div>
        <h3>{done ? "Refund promise fulfilled" : payment.approval ? `${money(payment.approval.amount)} approved` :
          payment.canReview ? `Review ${money(payment.basis?.recommended_refund_amount)} refund` :
          execution && ["unknown", "pending", "submitting", "reserved"].includes(execution.status) ? "Refund outcome pending" :
          needsReview ? "Review the evidence" : "Check before approving"}</h3>
        <p>{done ? "The confirmed amount matches the promise." : payment.approval ? "Review the approved amount before submitting." : payment.nextMessage}</p></div>
      <div className="action-buttons">
        {payment.canSubmit && <Button variant="primary" onClick={payment.onSubmit} disabled={payment.busy}>Review submission <ArrowRight size={16} /></Button>}
        {payment.canSubmit && payment.onSimulateOutside && <Button variant="ghost" onClick={payment.onSimulateOutside} disabled={payment.busy}>
          <ArrowLeftRight size={14} /> Simulate outside refund</Button>}
        {payment.canReview && !payment.canSubmit && <Button variant="primary" onClick={payment.onReview} disabled={payment.busy}>Review refund <ArrowRight size={16} /></Button>}
        {!done && !payment.canReview && !payment.canSubmit && execution?.provider_refund?.refund_id && execution.status !== "completed"
          ? <Button onClick={payment.onCheckExecution} disabled={payment.busy}><RefreshCw size={15} /> Check status</Button>
          : !done && !payment.canReview && !payment.canSubmit && <Button onClick={payment.onRefresh} disabled={payment.busy}><RefreshCw size={15} /> Refresh evidence</Button>}
      </div>
    </section>
    {payment.error && <Notice>{payment.error}</Notice>}
  </>;
}

function PromiseCards({ item, onAdd, onEdit, onEvidence, onRefresh, refreshing }: Pick<DeskProps, "item" | "onAdd" | "onEdit" | "onEvidence" | "onRefresh" | "refreshing">) {
  const [first] = item.promises;
  return <section className="section-card promise-section">
    <div className="section-head"><div><div className="eyebrow">THE AGREEMENT</div><h3>Promises &amp; evidence</h3></div>
      <Button onClick={onAdd} className="small-button"><Plus size={15} /> Add promise</Button></div>
    {!first && <Empty title="No promises recorded yet" detail="Record the remedy you agreed on and the evidence that supports it." />}
    <div className="promise-list">
      {item.promises.map((p) => {
        const Icon = remedyIcons[p.terms.target.kind];
        const canRefresh = p.terms.target.kind !== "return" || !!p.terms.target.tracking;
        return <details className="promise-row" key={p.id}>
          <summary><span className="promise-icon"><Icon size={18} /></span>
            <span className="promise-title"><strong>{remedyLabels[p.terms.target.kind]}</strong><span>{p.terms.promise}</span></span>
            <Badge outcome={p.outcome} /><ChevronDown className="promise-chevron" size={16} /></summary>
          <div className="promise-detail">
            <div className="promise-meta"><span>{sourceLabels[p.evidence_source]}</span><span>Revision {p.revision}</span>
              {p.terms.due_at && <span className={p.overdue ? "overdue" : ""}><CalendarDays size={14} /> Due {dateText(p.terms.due_at)}{p.overdue ? " · Overdue" : ""}</span>}</div>
            <p className="promise-reason">{p.reason}</p>
            <blockquote>{p.terms.source_note}{p.terms.source_reference && <cite>{p.terms.source_reference}</cite>}</blockquote>
            {p.terms.requires.length > 0 && <p className="prerequisite-note"><ListChecks size={15} /> Requires {p.terms.requires.map((id) => item.promises.find((entry) => entry.id === id)?.terms.target.kind)
              .filter((kind): kind is NonNullable<typeof kind> => !!kind).map((kind) => remedyLabels[kind]).join(", ")}</p>}
            {p.provider_proofs.map((proof, index) => <div className="proof-row" key={proof.resource_id + index}>
              <ShieldCheck size={16} /><div><strong>{proof.provider === "paypal" ? "PayPal" : proof.provider === "easypost" ? "EasyPost" : pretty(proof.provider)} · {pretty(proof.status)}</strong>
                <small>{proof.detail}{proof.response_due_at ? ` · Response due ${timeText(proof.response_due_at)}` : ""}</small></div>
              {proof.amount && <strong>{money(proof.amount, proof.currency ?? "USD")}</strong>}</div>)}
            <div className="promise-actions">
              <Button onClick={() => onEvidence(p)} className="small-button">Record evidence</Button>
              <Button onClick={() => onEdit(p)} className="small-button" variant="ghost">Revise</Button>
              {canRefresh && <Button onClick={() => onRefresh(p)} className="small-button" variant="ghost" disabled={!!refreshing}>
                <RefreshCw size={14} className={refreshing === p.id ? "spin" : ""} /> {refreshing === p.id ? "Checking…" : "Check provider"}</Button>}
            </div>
          </div>
        </details>;
      })}
    </div>
  </section>;
}

const eventNames: Record<string, string> = {
  case_created: "Case opened", promise_recorded: "Promise recorded", promise_revised: "Promise revised", merchant_evidence: "Evidence recorded",
  provider_observation: "Provider evidence checked", verification_failed: "Verification needs review", refund_approved: "Refund approved",
  approved: "Refund approved", completed: "Refund completed", verified: "Provider verification", invalidated: "Approval invalidated",
  "case.created": "Payment case opened",
};

function caseEvents(timeline: Timeline | null) {
  return [
    ...(timeline?.items ?? []).map((event) => ({ ...event, time: event.recorded_at, actor: sourceLabels[event.source], checked: event.source === "provider_confirmed" })),
    ...(timeline?.refund_items ?? []).map((event) => ({ ...event, time: event.occurred_at,
      actor: event.actor_kind === "merchant" ? "Merchant recorded" : event.source.endsWith("_verification") ? "Provider confirmed" : "Resolve",
      checked: event.source.endsWith("_verification") })),
  ].sort((a, b) => Date.parse(b.time) - Date.parse(a.time));
}

const RECENT_EVENTS = 6;
// Overview preview of the already-loaded events: title, source and time only. Details stay in the timeline tab.
function RecentActivity({ timeline, timelineError, onOpen }: Pick<DeskProps, "timeline" | "timelineError"> & { onOpen: () => void }) {
  const events = caseEvents(timeline);
  return <div className="section-card activity-card">
    {timelineError && <p className="panel-state">Events could not be loaded. Open the evidence timeline to retry.</p>}
    {!timeline && !timelineError && <p className="panel-state" role="status">Loading events…</p>}
    {timeline && !events.length && <p className="panel-state">No events recorded yet.</p>}
    {!!events.length && <ol className="event-list event-list-compact">{events.slice(0, RECENT_EVENTS).map((event) =>
      <li key={event.id}><span className={`event-dot ${event.checked ? "event-provider" : ""}`} aria-hidden="true" />
        <div><strong>{eventNames[event.event_type] ?? pretty(event.event_type)}</strong>
          <small>{event.actor} · <time dateTime={event.time}>{timeText(event.time)}</time></small></div></li>)}</ol>}
    {!!events.length && <Button variant="ghost" className="small-button" onClick={onOpen}>See all events <ArrowRight size={14} /></Button>}
  </div>;
}

function EventTimeline({ timeline, timelineError, loadMore, loadingTimeline, onExport }: Pick<DeskProps, "timeline" | "timelineError" | "loadMore" | "loadingTimeline" | "onExport">) {
  const events = caseEvents(timeline);
  return <section className="section-card timeline-card">
    <div className="section-head"><div><div className="eyebrow">AUDIT TRAIL</div><h3>Evidence timeline</h3></div>
      <Button onClick={onExport} className="small-button"><ArrowDownToLine size={15} /> Export evidence</Button></div>
    {timelineError && <Notice>{timelineError}</Notice>}
    {!timeline && !timelineError && <p className="muted">Loading evidence…</p>}
    {timeline && !events.length && <Empty title="No evidence yet" detail="New promises, observations and approvals will appear here." />}
    <ol className="event-list">{events.map((event) => {
      const description = ["note", "detail", "promise", "reason", "status_reason"].map((key) => event.data[key]).find((entry) => typeof entry === "string");
      return <li key={event.id}><span className={`event-icon ${event.checked ? "event-provider" : ""}`}>{event.checked ? <ShieldCheck size={16} /> : <FileText size={15} />}</span>
        <div><div className="event-title"><strong>{eventNames[event.event_type] ?? pretty(event.event_type)}</strong><time dateTime={event.time}>{timeText(event.time)}</time></div>
          <small>{event.actor}</small>{typeof description === "string" && <p>{description}</p>}</div></li>;
    })}</ol>
    {timeline && (timeline.items.length < timeline.total || timeline.refund_items.length < timeline.refund_total) &&
      <Button onClick={loadMore} disabled={loadingTimeline}>{loadingTimeline ? "Loading…" : "Load more events"}</Button>}
  </section>;
}

function Receipt({ item, demo }: { item: CaseView; demo: boolean }) {
  const progress = item.promises.find((p) => p.refund_progress)?.refund_progress;
  return <section className="receipt-view">
    <div className="section-card receipt-toolbar"><div><div className="eyebrow">CUSTOMER VIEW</div><h3>Buyer receipt</h3></div>
      <Button onClick={() => window.print()}><Printer size={16} /> Print or save PDF</Button></div>
    <article className="receipt-sheet" aria-label="Buyer receipt">
      <div className="receipt-top"><Brand small /><span className="provider-chip">{demo ? "Sample receipt" : "Resolution update"}</span></div>
      <h3>Resolution summary</h3><p>Here is the current status of the agreement for your order.</p>
      <div className="receipt-order"><span>Order reference <strong>{item.order_reference ?? "—"}</strong></span><Badge outcome={item.outcome} /></div>
      {progress && <dl className="receipt-amounts"><div><dt>Refund agreed</dt><dd>{money(progress.promised_amount)}</dd></div>
        <div><dt>{demo ? "Refund confirmed in demo" : "Refund confirmed by PayPal"}</dt><dd>{money(progress.provider_completed_amount)}</dd></div>
        <div><dt>Still owed</dt><dd>{money(progress.outstanding_amount)}</dd></div></dl>}
      <ul className="receipt-promises">{item.promises.map((p) => <li key={p.id}><span>{p.terms.promise}</span><strong>{outcomeLabels[p.outcome]}</strong></li>)}</ul>
      {demo ? <p className="receipt-note">This is a sample. No money moved.</p> : progress && <p className="receipt-note">After PayPal confirms a refund, it may take additional time to appear on your original payment method.</p>}
    </article>
  </section>;
}

export function CaseDesk(props: DeskProps) {
  const { item, tab, setTab, demo, onBack, error, verifiedMessage } = props;
  const ops = item.operations;
  const due = ops?.due_at ?? ops?.promise_due_at;
  return <section className="case-desk" aria-label="Selected case">
    <Button variant="ghost" className="mobile-back" onClick={onBack}><ArrowLeft size={17} /> Back to inbox</Button>
    <header className="case-heading"><div className="case-kicker"><span><Fingerprint size={15} /> Case {shortId(item.id)}</span><Badge outcome={item.outcome} /></div>
      <h2>{item.title}</h2><div className="case-meta"><span><PackageCheck size={15} /> {item.order_reference ?? "No order reference"}</span>
        <span><CalendarDays size={15} /> Opened {dateText(item.created_at)}</span></div>
      {ops && <div className="triage-strip">
        <div><strong>{workflowLabels[ops.workflow]}</strong><span>{ops.assignee ? "Assigned to " + ops.assignee : "Unassigned"}
          {due && ops.workflow !== "resolved" && <span className={ops.overdue ? "overdue" : ""}> · {ops.overdue ? "Overdue: " : "Due: "}{timeText(due)}</span>}</span></div>
        <Button className="small-button" onClick={props.onManage}>Manage case</Button>
      </div>}
    </header>
    <nav className="case-tabs" aria-label="Case views">
      {([["overview", "Overview"], ["timeline", "Evidence timeline"], ["receipt", "Buyer receipt"], ["customer", "Customer portal"]] as const).map(([key, label]) => (
        <button type="button" key={key} className={tab === key ? "active" : ""} aria-current={tab === key ? "page" : undefined}
          onClick={() => setTab(key)}>{label}{key === "receipt" && <ArrowUpRight size={13} />}</button>))}
    </nav>
    <div className="desk-content">
      {error && <Notice>{error}</Notice>}
      {verifiedMessage && <Notice tone="success">{verifiedMessage}</Notice>}
      {tab === "overview" && <div className="case-overview">
        <section className="desk-area area-summary" aria-labelledby="area-summary-title">
          <h3 className="area-title" id="area-summary-title">Case summary</h3>
          {!item.refund_case_id && <div className="section-card linked-panel customer-print-hide">
            <span className="section-icon"><Wallet size={19} /></span><div><strong>No payment linked</strong><p>Link the payment if this case needs a refund.</p></div>
            <Button className="small-button" onClick={props.onLinkPayment}>Link payment record</Button></div>}
          <PaymentPanel {...props} />
        </section>
        <section className="desk-area area-promises" aria-labelledby="area-promises-title">
          <h3 className="area-title" id="area-promises-title">Promises &amp; AI</h3>
          <PromiseCards {...props} />
          {props.assistant}
          {!demo && <HelpdeskPanel key={item.id} caseId={item.id} request={props.request} />}
        </section>
        <section className="desk-area area-timeline" aria-labelledby="area-timeline-title">
          <h3 className="area-title" id="area-timeline-title">Timeline</h3>
          <RecentActivity {...props} onOpen={() => setTab("timeline")} />
        </section>
      </div>}
      {tab === "timeline" && <EventTimeline {...props} />}
      {tab === "receipt" && <Receipt item={item} demo={demo} />}
      {tab === "customer" && <MerchantCustomer key={item.id} item={item} request={props.request} demo={demo} onOperations={props.onOperations} />}
    </div>
  </section>;
}
