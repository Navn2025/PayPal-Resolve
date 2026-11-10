"use client";

import { useEffect, useState } from "react";
import { money, type Requester } from "@/lib/domain";
import { Button, Notice } from "./ui";

export type HealthStatus = "kept" | "partially_kept" | "at_risk" | "broken";
export type PromiseHealth = {
  case_id: string; promise_id: string; promise: string; status: HealthStatus; currency: string;
  promised_amount: string; refunded_amount: string; pending_amount: string; remaining_amount: string;
  captured_amount: string; suggested_refund_amount: string; deadline: string; days_since_promise: number;
  overdue: boolean; ledger_ahead_of_provider: boolean;
};
type CaseHealth = { case_id: string; overdue_after_days: number; items: PromiseHealth[] };
type Missing = { code: string; text: string; promise_id: string | null };
type NextAction = { case_id: string; missing: Missing[]; summary: string };
type Explanation = { text: string; source: "ai" | "template"; label: string | null; fallback_reason: string | null; cache_hit: boolean };

const fallbackText: Record<string, string> = {
  extraction_disabled: "AI is turned off on this server", not_configured: "AI is not set up on this server",
  data_policy_blocked: "the data policy does not allow the AI provider", budget_exceeded: "today's AI budget is used up",
  fact_guard: "the AI text mentioned a value that is not in the case facts", invalid_json: "the AI answer could not be read",
};

const statusLabels: Record<HealthStatus, string> = {
  kept: "Kept", partially_kept: "Partially kept", at_risk: "At risk", broken: "Broken",
};
const statusBadge: Record<HealthStatus, string> = {
  kept: "badge-fulfilled", partially_kept: "badge-pending", at_risk: "badge-needs_review", broken: "badge-broken",
};
const days = (count: number) => `${count} ${count === 1 ? "day" : "days"}`;
const cents = (value: string) => Math.round(Number(value) * 100);

/** Read-only check of each accepted refund promise against refunds on the linked payment. */
export function PromiseHealthPanel({ caseId, request, refreshKey, canRefund, blockedReason, onRefund }: {
  caseId: string; request: Requester; refreshKey?: string; canRefund: boolean; blockedReason: string;
  onRefund: (amount: string) => void;
}) {
  const [health, setHealth] = useState<CaseHealth | null>(null);
  const [next, setNext] = useState<NextAction | null>(null);
  // The explanation is kept with the summary it was written for, so a reload of unchanged facts keeps it.
  const [explanation, setExplanation] = useState<(Explanation & { forSummary: string }) | null>(null);
  const [explaining, setExplaining] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    Promise.all([request<CaseHealth>(`/resolution-cases/${caseId}/promise-health`), request<NextAction>(`/resolution-cases/${caseId}/next-action`)])
      .then(([value, action]) => { if (active) { setHealth(value); setNext(action); setError(""); } })
      .catch((failure) => { if (active) setError(failure instanceof Error ? failure.message : "Promise check is unavailable."); });
    return () => { active = false; };
  }, [caseId, request, refreshKey]);
  async function explainStep() {
    if (!next) return;
    const forSummary = next.summary;
    setExplaining(true); setError("");
    try { setExplanation({ ...await request<Explanation>(`/resolution-cases/${caseId}/ai/explain-next-action`, "POST"), forSummary }); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "The explanation is unavailable."); }
    finally { setExplaining(false); }
  }

  const loading = !health && !next && !error;
  const current = next && explanation?.forSummary === next.summary ? explanation : null;
  return <section className="ai-group promise-health" aria-label="Promise check" aria-busy={loading}>
    <article className="ai-card">
      <header className="card-head"><div><div className="eyebrow">BROKEN-PROMISE CHECK</div><h3>Promise check</h3></div></header>
      {error && <Notice>{error}</Notice>}
      {loading && <p className="panel-state" role="status">Checking promises…</p>}
      {health && !health.items.length && <p className="panel-state">No accepted refund promise on a linked payment to check.</p>}
      {health?.items.map((item) => {
        const owed = item.status !== "kept";
        const suggested = item.suggested_refund_amount;
        const capped = cents(suggested) < cents(item.remaining_amount);
        return <article className={`health-card health-${item.status}`} key={item.promise_id} aria-label={`Promise ${statusLabels[item.status]}`}>
          <div className="health-head"><strong>{item.promise}</strong><span className={`badge ${statusBadge[item.status]}`}><span />{statusLabels[item.status]}</span></div>
          <dl className="money-rows">
            <div><dt>Promised</dt><dd>{money(item.promised_amount, item.currency)}</dd></div>
            <div><dt>Refunded</dt><dd>{money(item.refunded_amount, item.currency)}</dd></div>
            {Number(item.pending_amount) > 0 && <div><dt>Pending with PayPal</dt><dd>{money(item.pending_amount, item.currency)}</dd></div>}
            {owed && <div className="money-row-total"><dt>At risk</dt><dd>{money(item.remaining_amount, item.currency)}</dd></div>}
            <div><dt>Days since promise</dt><dd>{days(item.days_since_promise)}</dd></div>
          </dl>
          <p className="card-note">
            {item.overdue ? `Past its deadline (${new Date(item.deadline).toLocaleDateString()}).`
              : owed ? `Due by ${new Date(item.deadline).toLocaleDateString()} (${health.overdue_after_days}-day window unless a due date was set).` : "The confirmed refunds cover the promise."}
          </p>
          {item.ledger_ahead_of_provider && <Notice tone="info">More refunds are recorded on the payment than PayPal has confirmed. Check the evidence before refunding again.</Notice>}
          {owed && cents(suggested) > 0 && <div className="card-actions">
            <Button variant="primary" disabled={!canRefund} onClick={() => onRefund(suggested)}>Refund remaining {money(suggested, item.currency)}</Button>
            <small className={canRefund ? "" : "disabled-reason"}>{canRefund ? "Opens the refund review with this amount. Nothing is sent until you approve and submit."
              : `Refund review is not available yet: ${blockedReason}`}</small>
          </div>}
          {owed && capped && <p className="card-note">Limited to {money(suggested, item.currency)} by refunds already recorded or pending and the {money(item.captured_amount, item.currency)} captured.</p>}
        </article>;
      })}
    </article>
    <article className="ai-card missing-list">
      <header className="card-head"><div><div className="eyebrow">BEFORE ANY REFUND</div><h3>Missing before refund</h3></div>
        {next && <span className={`badge ${next.missing.length ? "badge-needs_review" : "badge-fulfilled"}`}><span />{next.missing.length ? `${next.missing.length} open` : "Complete"}</span>}</header>
      {loading && <p className="panel-state" role="status">Checking what is missing…</p>}
      {next && !next.missing.length && <p className="panel-state">Nothing is missing before a refund.</p>}
      {!!next?.missing.length && <ul>{next.missing.map((item, index) => <li key={item.code + index} data-code={item.code}>{item.text}</li>)}</ul>}
    </article>
    <article className="ai-card next-step">
      <header className="card-head"><div><div className="eyebrow">RECOMMENDATION</div><h3>Next step</h3></div>
        {current?.source === "ai" && <span className="badge badge-needs_review ai-label"><span />{current.label}</span>}</header>
      {loading && <p className="panel-state" role="status">Working out the next step…</p>}
      {next && <p className="next-step-text">{current?.text ?? next.summary}</p>}
      {current?.source === "template" && <p className="card-note">Written from case facts. AI explanation not used: {fallbackText[current.fallback_reason ?? ""] ?? current.fallback_reason?.replace(/_/g, " ")}.</p>}
      {next && <div className="card-actions"><Button disabled={explaining} aria-busy={explaining} onClick={() => void explainStep()}>{explaining ? "Explaining…" : "Explain with AI"}</Button>
        <small>Advisory only. It never approves or sends a refund.</small></div>}
    </article>
  </section>;
}
