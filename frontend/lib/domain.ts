export type Outcome = "waiting" | "pending" | "fulfilled" | "needs_review";
export type Remedy = "refund" | "return" | "replacement" | "order_cancellation" | "subscription" | "store_credit_or_exchange" | "billing_correction" | "dispute_handoff";
export type Source = "merchant_recorded" | "provider_confirmed" | "system";
export type Target = { kind: Remedy; [key: string]: unknown };

export interface Terms {
  promise: string;
  source_note: string;
  source_reference?: string | null;
  due_at?: string | null;
  requires: string[];
  target: Target;
}
export interface Proof {
  provider: string;
  resource_id: string;
  status: string;
  outcome: Outcome;
  detail: string;
  environment?: string | null;
  response_due_at?: string | null;
  amount?: string | null;
  currency?: string | null;
}
export interface RefundProgress {
  refund_case_id: string;
  captured_amount: string;
  promised_amount: string;
  provider_completed_amount: string;
  provider_pending_amount: string;
  outstanding_amount: string;
  history_current: boolean;
  verified_remaining_refundable_amount: string | null;
  refund_ids: string[];
}
export interface PromiseView {
  id: string;
  revision: number;
  terms: Terms;
  outcome: Outcome;
  evidence_source: Source;
  reason: string;
  checked_at?: string | null;
  overdue: boolean;
  provider_proofs: Proof[];
  refund_progress: RefundProgress | null;
  created_at: string;
  updated_at: string;
}
export interface CaseSummary {
  id: string;
  title: string;
  order_reference: string | null;
  refund_case_id: string | null;
  created_at: string;
}
export interface CaseView extends CaseSummary {
  operations?: import("./customer").Operations;
  outcome: Outcome;
  promises: PromiseView[];
}
export interface Page<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}
export interface CaseEvent {
  id: string;
  promise_id: string | null;
  revision: number | null;
  event_type: string;
  source: Source;
  actor_merchant_id: string | null;
  recorded_at: string;
  data: Record<string, unknown>;
}
export interface RefundEvent {
  id: string;
  event_type: string;
  source: string;
  actor_kind: string;
  actor_merchant_id: string | null;
  occurred_at: string;
  data: Record<string, unknown>;
}
export interface Timeline extends Page<CaseEvent> {
  refund_items: RefundEvent[];
  refund_total: number;
}
export interface LegacyCase {
  id: string;
  order_id: string;
  complaint: string;
  status: "open" | "closed";
  payment: { capture_id: string; captured_amount: string; currency: "USD" };
  commitment?: { amount: string; currency: "USD"; status: string; source_message: string } | null;
}
export interface Reconciliation {
  state_fingerprint: string;
  currency: "USD";
  status: string;
  next_action: string;
  recommended_refund_amount: string;
  paypal_history_current: boolean;
  active_refund_execution_id: string | null;
}
export interface Approval {
  id: string;
  capture_id: string;
  amount: string;
  currency: "USD";
  status: "approved" | "revoked" | "expired" | "invalidated";
  state_fingerprint: string;
  expires_at: string;
}
export interface Execution {
  id: string;
  approval_id: string;
  amount: string;
  status: "reserved" | "submitting" | "unknown" | "pending" | "completed" | "failed";
  provider_refund: { refund_id: string; provider_status: string; amount: string } | null;
  error_code?: string | null;
  updated_at: string;
}
export interface Review {
  id: string;
  case_id: string | null;
  capture_id: string | null;
  reason: string;
  blocking: boolean;
  status: "open" | "resolved";
  updated_at: string;
}
export interface Merchant { id: string; name: string }
export interface Session {
  merchant: Merchant | null;
  method?: "key" | "paypal";
  expires_at?: string;
  paypal_linked?: boolean;
  paypal_enabled?: boolean;
  paypal_environment?: "sandbox" | "live" | null;
}
export type Requester = <T>(path: string, method?: "GET" | "POST" | "PUT" | "DELETE", data?: unknown) => Promise<T>;

export const remedyLabels: Record<Remedy, string> = {
  refund: "Refund", return: "Return milestone", replacement: "Replacement",
  order_cancellation: "Order cancellation", subscription: "Subscription",
  store_credit_or_exchange: "Store credit or exchange", billing_correction: "Billing correction",
  dispute_handoff: "Dispute handoff",
};
export const outcomeLabels: Record<Outcome, string> = {
  waiting: "Action needed", pending: "Pending verification", fulfilled: "Fulfilled", needs_review: "Needs review",
};
export const sourceLabels: Record<Source, string> = {
  merchant_recorded: "Merchant recorded", provider_confirmed: "Provider confirmed", system: "Resolve",
};
export const reconcileLabels: Record<string, string> = {
  refund_required: "The remaining amount is ready for merchant review.",
  awaiting_prerequisite: "Complete the prerequisite promise before approving a refund.",
  awaiting_condition: "Verify the agreed condition before approving a refund.",
  awaiting_acceptance: "Record the accepted agreement before requesting approval.",
  execution_pending: "An earlier submission is still being reconciled.",
  refund_pending: "PayPal is still processing a refund for this payment.",
  execution_failed: "Review the previous refund attempt before proceeding.",
  promise_review: "The resolution promise needs review before a refund can be approved.",
  provider_review: "The latest provider evidence needs review.",
  fulfilled: "The recorded agreement has been fulfilled.",
  closed: "This linked payment case is closed.",
  no_commitment: "The linked payment case does not have an agreed refund amount.",
};
export const money = (value: string | number | null | undefined, currency = "USD") =>
  value == null ? "—" : new Intl.NumberFormat("en-US", { style: "currency", currency }).format(Number(value));
export const pretty = (value: string) => value.replace(/[_-]/g, " ").toLowerCase().replace(/^./, (c) => c.toUpperCase());
export const shortId = (value: string) => value.startsWith("demo-") ? value.split("-").at(-1)! : value.slice(0, 7).toUpperCase();
export const dateText = (value?: string | null) => value ? new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" }).format(new Date(value)) : "—";
export const timeText = (value?: string | null) => value ? new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone: "UTC" }).format(new Date(value)) + " UTC" : "Not checked yet";
export const uuid = () => globalThis.crypto.randomUUID();
export function amountCents(value: string) {
  const result = /^(\d{1,10})(?:\.(\d{1,2}))?$/.exec(value.trim());
  return result ? Number(result[1]) * 100 + Number((result[2] ?? "").padEnd(2, "0")) : null;
}
export const centsText = (value: number) => (value / 100).toFixed(2);

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export function activeApproval(approvals: Approval[], executions: Execution[], basis?: Reconciliation | null) {
  return approvals.find((approval) => approval.status === "approved" && new Date(approval.expires_at).getTime() > Date.now()
    && approval.state_fingerprint === basis?.state_fingerprint && !executions.some((execution) => execution.approval_id === approval.id));
}
