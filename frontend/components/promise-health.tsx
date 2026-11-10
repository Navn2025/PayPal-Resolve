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
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    request<CaseHealth>(`/resolution-cases/${caseId}/promise-health`)
      .then((value) => { if (active) { setHealth(value); setError(""); } })
      .catch((failure) => { if (active) setError(failure instanceof Error ? failure.message : "Promise check is unavailable."); });
    return () => { active = false; };
  }, [caseId, request, refreshKey]);

  return <section className="section-card investigation-panel promise-health" aria-label="Promise check">
    <div className="section-head"><div><div className="eyebrow">BROKEN-PROMISE CHECK</div><h2>Promise check</h2></div></div>
    {error && <Notice>{error}</Notice>}
    {!health && !error && <p className="muted">Checking promises…</p>}
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
