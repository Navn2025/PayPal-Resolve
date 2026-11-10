"use client";

import { useEffect, useState } from "react";
import { dateText, type Requester } from "@/lib/domain";

export type HealthStatus = "kept" | "partially_kept" | "at_risk" | "broken";
export type PromiseHealth = {
  case_id: string; case_title?: string; promise_id: string; promise: string; status: HealthStatus; currency: string;
  promised_amount: string; refunded_amount: string; pending_amount: string; remaining_amount: string;
  captured_amount: string; suggested_refund_amount: string; deadline: string; days_since_promise: number;
  overdue: boolean; ledger_ahead_of_provider: boolean;
};
export type CaseHealth = { case_id: string; overdue_after_days: number; items: PromiseHealth[] };
export type Missing = { code: string; text: string; promise_id: string | null };
type RefundFacts = { promise_id: string; due_date: string | null };
export type NextAction = { case_id: string; missing: Missing[]; summary: string; facts: { refunds: RefundFacts[] } };
export type Explanation = { text: string; source: "ai" | "template"; label: string | null; fallback_reason: string | null; cache_hit: boolean };

export const statusLabels: Record<HealthStatus, string> = {
  kept: "Kept", partially_kept: "Partially kept", at_risk: "At risk", broken: "Broken",
};
export const statusBadge: Record<HealthStatus, string> = {
  kept: "badge-fulfilled", partially_kept: "badge-pending", at_risk: "badge-needs_review", broken: "badge-broken",
};
export const fallbackText: Record<string, string> = {
  extraction_disabled: "AI is turned off on this server", not_configured: "AI is not set up on this server",
  data_policy_blocked: "the data policy does not allow the AI provider", budget_exceeded: "today's AI budget is used up",
  fact_guard: "the AI text mentioned a value that is not in the case facts", invalid_json: "the AI answer could not be read",
};
export const cents = (value: string) => Math.round(Number(value) * 100);
export const days = (count: number) => `${count} ${count === 1 ? "day" : "days"}`;
const order: HealthStatus[] = ["broken", "at_risk", "partially_kept", "kept"];
export const worst = (items: PromiseHealth[]) => [...items].sort((a, b) => order.indexOf(a.status) - order.indexOf(b.status))[0];

/** "Due Nov 13" plus the rule behind the date, for a tooltip. */
export function dueLabel(item: PromiseHealth, health: CaseHealth, next: NextAction | null) {
  const agreed = next?.facts.refunds.some((fact) => fact.promise_id === item.promise_id && fact.due_date);
  const day = dateText(item.deadline);
  return {
    text: item.status === "kept" ? "" : item.overdue ? `Overdue since ${day}` : `Due ${day}`,
    rule: agreed ? "The due date agreed on the promise."
      : `No due date was set, so Resolve counts ${health.overdue_after_days} days from when the promise was recorded.`,
  };
}

/** Promise health, missing information and the next-step explanation for one case. Merchant mode only. */
export function useCaseChecks(caseId: string, request: Requester, refreshKey: string | undefined, enabled: boolean) {
  const [health, setHealth] = useState<CaseHealth | null>(null);
  const [next, setNext] = useState<NextAction | null>(null);
  // An explanation belongs to the case and the summary it was written for; reloads of unchanged facts keep it.
  const [explanation, setExplanation] = useState<(Explanation & { forCase: string; forSummary: string }) | null>(null);
  const [explaining, setExplaining] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!enabled) return;
    let active = true;
    Promise.all([request<CaseHealth>(`/resolution-cases/${caseId}/promise-health`), request<NextAction>(`/resolution-cases/${caseId}/next-action`)])
      .then(([value, action]) => { if (active) { setHealth(value); setNext(action); setError(""); } })
      .catch((failure) => { if (active) setError(failure instanceof Error ? failure.message : "Promise check is unavailable."); });
    return () => { active = false; };
  }, [caseId, request, refreshKey, enabled]);
  const current = next?.case_id === caseId ? next : null;
  const currentHealth = health?.case_id === caseId ? health : null;
  async function explain() {
    if (!current) return;
    const forSummary = current.summary;
    setExplaining(true); setError("");
    try { setExplanation({ ...await request<Explanation>(`/resolution-cases/${caseId}/ai/explain-next-action`, "POST"), forCase: caseId, forSummary }); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "The explanation is unavailable."); }
    finally { setExplaining(false); }
  }
  return {
    enabled, health: currentHealth, next: current, error, explaining, explain,
    loading: enabled && !current && !currentHealth && !error,
    explanation: explanation && current && explanation.forCase === caseId && explanation.forSummary === current.summary ? explanation : null,
  };
}
export type CaseChecks = ReturnType<typeof useCaseChecks>;
