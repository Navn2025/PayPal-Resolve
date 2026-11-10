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

  return <section className="section-card investigation-panel promise-health" aria-label="Promise check">
    <div className="section-head"><div><div className="eyebrow">BROKEN-PROMISE CHECK</div><h2>Promise check</h2></div></div>
    {error && <Notice>{error}</Notice>}
    {!health && !error && <p className="muted">Checking promises…</p>}
    {next && (() => { const current = explanation?.forSummary === next.summary ? explanation : null; return <div className="next-step">
      <h3>Next step</h3>
      {current?.source === "ai"
        ? <><span className="badge badge-needs_review ai-label">{current.label}</span><p>{current.text}</p></>
        : <p>{current?.text ?? next.summary}</p>}
      {current?.source === "template" && <small className="muted">Written from case facts. AI explanation not used: {fallbackText[current.fallback_reason ?? ""] ?? current.fallback_reason?.replace(/_/g, " ")}.</small>}
      <div className="health-actions"><Button disabled={explaining} onClick={() => void explainStep()}>{explaining ? "Explaining…" : "Explain with AI"}</Button>
        <small>Advisory only. It never approves or sends a refund.</small></div>
    </div>; })()}
    {!!next?.missing.length && <div className="missing-list"><h3>Missing before refund</h3>
      <ul>{next.missing.map((item, index) => <li key={item.code + index} data-code={item.code}>{item.text}</li>)}</ul></div>}
    {health && !health.items.length && <p className="muted">No accepted refund promise on a linked payment to check.</p>}
    {health?.items.map((item) => {
      const owed = item.status !== "kept";
      const suggested = item.suggested_refund_amount;
      const capped = cents(suggested) < cents(item.remaining_amount);
      return <article className={`health-card health-${item.status}`} key={item.promise_id} aria-label={`Promise ${statusLabels[item.status]}`}>
        <div className="health-head"><strong>{item.promise}</strong><span className={`badge ${statusBadge[item.status]}`}><span />{statusLabels[item.status]}</span></div>
        <p className="health-line">
          Promised {money(item.promised_amount, item.currency)} · Refunded {money(item.refunded_amount, item.currency)}
          {owed && <> · <strong>{money(item.remaining_amount, item.currency)} at risk</strong></>} · {days(item.days_since_promise)}
        </p>
        <p className="muted">
          {item.overdue ? `Past its deadline (${new Date(item.deadline).toLocaleDateString()}).`
            : owed ? `Due by ${new Date(item.deadline).toLocaleDateString()} (${health.overdue_after_days}-day window unless a due date was set).` : "The confirmed refunds cover the promise."}
          {Number(item.pending_amount) > 0 && ` ${money(item.pending_amount, item.currency)} is still pending with PayPal.`}
        </p>
        {item.ledger_ahead_of_provider && <Notice tone="info">More refunds are recorded on the payment than PayPal has confirmed. Check the evidence before refunding again.</Notice>}
        {owed && cents(suggested) > 0 && <div className="health-actions">
          <Button variant="primary" disabled={!canRefund} onClick={() => onRefund(suggested)}>Refund remaining {money(suggested, item.currency)}</Button>
          <small>{canRefund ? "Opens the refund review with this amount. Nothing is sent until you approve and submit."
            : `Refund review is not available yet: ${blockedReason}`}</small>
        </div>}
        {owed && capped && <p className="muted">Limited to {money(suggested, item.currency)} by refunds already recorded or pending and the {money(item.captured_amount, item.currency)} captured.</p>}
      </article>;
    })}
  </section>;
}
