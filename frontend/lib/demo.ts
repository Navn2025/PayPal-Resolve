import { ApiError, activeApproval, amountCents, centsText, money, uuid } from "./domain";
import type { Approval, CaseEvent, CaseView, Execution, LegacyCase, Outcome, Page, PromiseView, Reconciliation, Requester, Review, Terms, Timeline } from "./domain";

const seedDate = "2026-11-07T08:30:00Z";
export const demoPrimary = "demo-1042";
const mainRefund = "demo-payment-1042";
const now = () => new Date().toISOString();
const page = <T>(items: T[], limit: number, offset: number): Page<T> => ({
  items: items.slice(offset, offset + limit), total: items.length, limit, offset,
});
const promise = (id: string, terms: Terms, outcome: Outcome, reason: string, extra: Partial<PromiseView> = {}): PromiseView => ({
  id, terms, outcome, reason, revision: 1, evidence_source: "merchant_recorded",
  provider_proofs: [], refund_progress: null, overdue: false, created_at: seedDate, updated_at: seedDate, ...extra,
});
const returnPromise = promise("demo-return", {
  promise: "Confirm that the returned headphones reached our warehouse.",
  source_note: "Warehouse intake confirmed the headphones were received and matched the return.",
  source_reference: "RMA-4821", requires: [],
  target: { kind: "return", milestone: "warehouse_received", return_reference: "RMA-4821" },
}, "fulfilled", "Warehouse receipt recorded by the merchant.", { checked_at: "2026-11-07T09:12:00Z" });
const refundPromise = promise("demo-refund", {
  promise: "Refund $30.00 once the returned headphones are received.",
  source_note: "We’ll refund $30.00 to your original payment method once the headphones are back at our warehouse.",
  source_reference: "Support ticket #1842", requires: ["demo-return"], target: { kind: "refund", amount: "30.00", currency: "USD" },
}, "waiting", "The return is confirmed. $20.00 of the refund is still owed.", {
  evidence_source: "provider_confirmed", checked_at: "2026-11-07T09:24:00Z",
  provider_proofs: [{ provider: "paypal", resource_id: "DEMOREFUND10", status: "COMPLETED", amount: "10.00", currency: "USD",
    outcome: "fulfilled", detail: "Previously issued in PayPal.", environment: "sandbox" }],
  refund_progress: { refund_case_id: mainRefund, captured_amount: "100.00", promised_amount: "30.00", provider_completed_amount: "10.00",
    provider_pending_amount: "0.00", outstanding_amount: "20.00", history_current: true, verified_remaining_refundable_amount: "90.00", refund_ids: ["DEMOREFUND10"] },
});
const demoCases: CaseView[] = [
  { id: demoPrimary, title: "Refund for returned headphones", order_reference: "ORD-4821", refund_case_id: mainRefund,
    created_at: "2026-11-07T09:24:00Z", outcome: "waiting", promises: [returnPromise, refundPromise] },
  { id: "demo-1041", title: "Duplicate charge reported", order_reference: "ORD-4819", refund_case_id: "demo-payment-1041",
    created_at: "2026-11-07T08:11:00Z", outcome: "needs_review", promises: [
      promise("demo-duplicate", { promise: "Check and correct the reported duplicate payment.", source_note: "Customer reported two charges.",
        requires: [], target: { kind: "billing_correction", action: "duplicate_charge" } },
      "needs_review", "Confirm which capture belongs to the original order before taking action.") ] },
  { id: "demo-1038", title: "Replacement for damaged lamp", order_reference: "ORD-4793", refund_case_id: null,
    created_at: "2026-11-06T13:35:00Z", outcome: "pending", promises: [
      promise("demo-replace", { promise: "Send a replacement lamp and confirm delivery.", source_note: "Replacement approved in support.",
        requires: [], target: { kind: "replacement", replacement_reference: "REPLACE-4793", milestone: "delivered" } }, "pending",
        "The carrier has the parcel. Delivery is still pending.", { evidence_source: "provider_confirmed",
          provider_proofs: [{ provider: "easypost", resource_id: "DEMO-TRACK", status: "IN_TRANSIT", detail: "The replacement is in transit.", outcome: "pending", environment: "test" }] }) ] },
  { id: "demo-1035", title: "Cancel a duplicate subscription", order_reference: "SUB-2108", refund_case_id: null,
    created_at: "2026-11-06T10:21:00Z", outcome: "fulfilled", promises: [
      promise("demo-sub", { promise: "Cancel the duplicate subscription.", source_note: "Customer requested cancellation.",
        requires: [], target: { kind: "subscription", action: "cancel", paypal_subscription_id: "DEMO-SUB" } },
      "fulfilled", "PayPal confirmed that the subscription is cancelled.", { evidence_source: "provider_confirmed",
        provider_proofs: [{ provider: "paypal", resource_id: "DEMO-SUB", status: "CANCELLED", outcome: "fulfilled",
          detail: "Cancellation was confirmed.", environment: "sandbox" }] }) ] },
  { id: "demo-1031", title: "Order cancelled before dispatch", order_reference: "ORD-4740", refund_case_id: null,
    created_at: "2026-11-05T11:20:00Z", outcome: "fulfilled", promises: [
      promise("demo-cancel", { promise: "Cancel the order and release the payment hold.", source_note: "Cancellation requested before dispatch.",
        requires: [], target: { kind: "order_cancellation", paypal_authorization_id: "DEMO-AUTH" } },
      "fulfilled", "The payment authorization was voided.", { evidence_source: "provider_confirmed",
        provider_proofs: [{ provider: "paypal", resource_id: "DEMO-AUTH", status: "VOIDED", outcome: "fulfilled", detail: "The authorization hold was released.", environment: "sandbox" }] }) ] },
];

type Operations = import("./customer").Operations;

export class DemoStore {
  private caseOperations = new Map<string, Pick<Operations, "assignee" | "due_at" | "waiting_on_customer" | "revision">>();
  private cases = structuredClone(demoCases);
  private payments: LegacyCase[] = [{
    id: mainRefund, order_id: "ORD-4821", complaint: "Refund for returned headphones", status: "open",
    payment: { capture_id: "DEMO-CAPTURE-4821", captured_amount: "100.00", currency: "USD" },
    commitment: { amount: "30.00", currency: "USD", status: "accepted", source_message: refundPromise.terms.source_note },
  }];
  private approvals: Approval[] = [];
  private executions: Execution[] = [];
  private paymentState = 1;
  private events: Record<string, CaseEvent[]> = {
    [demoPrimary]: [
      { id: "demo-event-3", promise_id: "demo-refund", revision: 1, event_type: "provider_observation",
        source: "provider_confirmed", actor_merchant_id: null, recorded_at: "2026-11-07T09:24:00Z", data: { note: "PayPal confirmed an earlier $10.00 refund." } },
      { id: "demo-event-2", promise_id: "demo-return", revision: 1, event_type: "merchant_evidence",
        source: "merchant_recorded", actor_merchant_id: "demo-merchant", recorded_at: "2026-11-07T09:12:00Z", data: { note: "Warehouse received return RMA-4821." } },
      { id: "demo-event-1", promise_id: "demo-refund", revision: 1, event_type: "promise_recorded",
        source: "merchant_recorded", actor_merchant_id: "demo-merchant", recorded_at: "2026-11-07T08:30:00Z", data: { promise: "Refund $30.00 after the return is received." } },
    ],
  };
  private reviews: Review[] = [{ id: "demo-review-1", case_id: "demo-payment-1041", capture_id: "DEMO-CAPTURE-4819",
    reason: "paypal_history_conflict", blocking: false, status: "open", updated_at: "2026-11-07T08:24:00Z" }];

  initial() { return structuredClone(this.cases); }
  private addEvent(caseId: string, type: string, source: CaseEvent["source"], data: CaseEvent["data"], item?: PromiseView) {
    (this.events[caseId] ??= []).unshift({
      id: uuid(), promise_id: item?.id ?? null, revision: item?.revision ?? null, event_type: type, source,
      actor_merchant_id: source === "merchant_recorded" ? "demo-merchant" : null, data, recorded_at: now(),
    });
  }
  private recalculate(item: CaseView) {
    item.outcome = item.promises.some((p) => p.outcome === "needs_review") ? "needs_review"
      : item.promises.some((p) => p.outcome === "pending") ? "pending"
      : item.promises.length > 0 && item.promises.every((p) => p.outcome === "fulfilled") ? "fulfilled" : "waiting";
  }
  private basis(id: string): Reconciliation {
    const item = this.cases.find((c) => c.refund_case_id === id);
    const refund = item?.promises.find((p) => p.terms.target.kind === "refund");
    const blocked = refund?.terms.requires.some((p) => item?.promises.find((x) => x.id === p)?.outcome !== "fulfilled");
    const current = id === mainRefund && !!refund?.refund_progress;
    const status = !current ? "no_commitment" : refund.outcome === "fulfilled" ? "fulfilled" : blocked ? "awaiting_prerequisite" : "refund_required";
    return { state_fingerprint: `demo-state-${this.paymentState}`, status, next_action: status === "refund_required" ? "request_merchant_approval" : "none",
      recommended_refund_amount: status === "refund_required" ? refund!.refund_progress!.outstanding_amount : "0.00",
      currency: "USD", paypal_history_current: current, active_refund_execution_id: null };
  }
  private invalidate() {
    this.paymentState += 1;
    this.approvals = this.approvals.map((a) => a.status === "approved" ? { ...a, status: "invalidated" } : a);
  }
  private finish(external: boolean, approvedAmount?: string) {
    const item = this.cases.find((c) => c.id === demoPrimary)!;
    const refund = item.promises.find((p) => p.id === "demo-refund")!;
    const progress = refund.refund_progress!;
    if (refund.outcome === "fulfilled") throw new ApiError(409, "The sample refund is already complete.");
    const outstanding = amountCents(progress.outstanding_amount)!;
    const delta = external ? outstanding : amountCents(approvedAmount ?? "");
    if (!delta || delta > outstanding) throw new ApiError(409, "The approved amount is outside the current demo balance.");
    const newId = external ? "DEMO-EXTERNAL-" + delta : "DEMO-RESOLVE-" + (this.executions.length + 1);
    progress.provider_completed_amount = centsText(amountCents(progress.provider_completed_amount)! + delta);
    progress.outstanding_amount = centsText(outstanding - delta);
    progress.verified_remaining_refundable_amount = centsText(amountCents(progress.verified_remaining_refundable_amount!)! - delta);
    progress.refund_ids.push(newId);
    refund.outcome = outstanding === delta ? "fulfilled" : "waiting";
    refund.reason = refund.outcome === "fulfilled" ? "The agreed refund amount is confirmed in this demo."
      : `${money(progress.outstanding_amount)} of the refund is still owed.`;
    refund.checked_at = now();
    refund.provider_proofs.push({ provider: "paypal", resource_id: newId, status: "COMPLETED", outcome: "fulfilled",
      detail: external ? "Simulated refund issued outside Resolve." : "Simulated refund submitted through Resolve.",
      amount: centsText(delta), currency: "USD", environment: "sandbox" });
    this.invalidate();
    this.recalculate(item);
    this.addEvent(item.id, "provider_observation", "provider_confirmed",
      { note: external ? `An external refund covered the remaining ${money(centsText(delta))}. Previous approval is stale.`
        : `The simulated ${money(centsText(delta))} refund completed.` }, refund);
    return newId;
  }
  simulateExternal() {
    if (!activeApproval(this.approvals, this.executions, this.basis(mainRefund))) throw new ApiError(409, "Approve the sample refund first.");
    this.finish(true);
  }
  private requestResult(path: string, method: string, input: unknown): unknown {
    const [route, query = ""] = path.split("?");
    const [, root, id, action, child, subaction] = route.split("/");
    const params = new URLSearchParams(query);
    const limit = Number(params.get("limit") ?? 25), offset = Number(params.get("offset") ?? 0);
    const data = (input ?? {}) as Record<string, unknown>;
    if (root === "review-queue") {
      if (method === "GET") return page(this.reviews.filter((i) => i.status === (params.get("status") ?? "open")), limit, offset);
      const review = this.reviews.find((i) => i.id === id);
      if (!review) throw new ApiError(404, "Review item not found.");
      review.status = "resolved";
      return review;
    }
    if (root === "cases") {
      if (method === "POST" && !id) {
        const item = { ...data, id: uuid(), status: "open" } as unknown as LegacyCase;
        this.payments.push(item);
        return item;
      }
      if (!id) return page(this.payments, limit, offset);
      const item = this.payments.find((c) => c.id === id);
      if (!item) throw new ApiError(404, "Payment case not found.");
      if (!action) return item;
      if (action === "reconciliation") return this.basis(id);
      if (action === "refund-approvals") {
        if (method === "GET") return id === mainRefund ? this.approvals : [];
        const basis = this.basis(id);
        const requested = amountCents(String(data.amount ?? ""));
        if (data.state_fingerprint !== basis.state_fingerprint || basis.status !== "refund_required" ||
          !requested || requested > amountCents(basis.recommended_refund_amount)!) {
          throw new ApiError(409, "This amount or approval no longer matches the current evidence.");
        }
        const approval: Approval = { id: uuid(), status: "approved", capture_id: item.payment.capture_id, currency: "USD",
          amount: data.amount as string, state_fingerprint: basis.state_fingerprint, expires_at: new Date(Date.now() + 900_000).toISOString() };
        this.approvals.unshift(approval);
        this.addEvent(demoPrimary, "refund_approved", "merchant_recorded", { note: `Approved ${money(approval.amount)} for the simulated refund.` });
        return approval;
      }
      if (action === "refund-executions") {
        if (method === "GET") return id === mainRefund ? this.executions : [];
        const approval = activeApproval(this.approvals, this.executions, this.basis(id));
        if (!approval || approval.id !== data.approval_id) throw new ApiError(409, "Approval is stale. No refund was submitted.");
        const refundId = this.finish(false, approval.amount);
        const execution: Execution = { id: uuid(), approval_id: approval.id, amount: approval.amount, status: "completed",
          provider_refund: { refund_id: refundId, provider_status: "COMPLETED", amount: approval.amount }, updated_at: now() };
        this.executions.unshift(execution);
        return execution;
      }
    }
    if (root === "resolution-cases") {
      if (!id && method === "GET") return page(this.cases, limit, offset);
      if (!id && method === "POST") {
        const item = { ...data, id: uuid(), created_at: now(), outcome: "waiting", promises: [] } as unknown as CaseView;
        this.cases.unshift(item);
        this.addEvent(item.id, "case_created", "merchant_recorded", { note: "Case created in the local demo." });
        return item;
      }
      const item = this.cases.find((c) => c.id === id);
      if (!item) throw new ApiError(404, "Resolution case not found.");
      if (!action) return item;
      const timeline: Timeline = { ...page(this.events[id] ?? [], limit, offset), refund_items: [], refund_total: 0 };
      if (action === "payment-link" && method === "PUT") {
        const payment = this.payments.find((entry) => entry.id === data.refund_case_id);
        if (!payment) throw new ApiError(404, "Payment case not found.");
        if (item.refund_case_id === payment.id) return item;
        if (item.refund_case_id || this.cases.some((entry) => entry.refund_case_id === payment.id)) {
          throw new ApiError(409, "The payment or case is already linked.");
        }
        item.refund_case_id = payment.id;
        this.addEvent(id, "payment_linked", "merchant_recorded", { note: "An existing payment was linked." });
        return item;
      }
      if (action === "operations") {
        let fields = this.caseOperations.get(id) ?? { assignee: null, due_at: null, waiting_on_customer: false, revision: 0 };
        if (method === "PUT") {
          if (data.expected_revision !== fields.revision) throw new ApiError(409, "Case settings changed. Reload the case.");
          fields = { assignee: data.assignee as string | null, due_at: data.due_at as string | null,
            waiting_on_customer: data.waiting_on_customer === true, revision: fields.revision + 1 };
          this.caseOperations.set(id, fields);
        }
        const basis = item.refund_case_id ? this.basis(item.refund_case_id) : null;
        const needsApproval = basis?.status === "refund_required" && !activeApproval(this.approvals, this.executions, basis);
        const workflow = item.outcome === "fulfilled" ? "resolved" : fields.waiting_on_customer ? "waiting_on_customer"
          : needsApproval ? "needs_approval" : "merchant_action";
        const promiseDue = item.promises.filter((p) => p.outcome !== "fulfilled" && p.terms.due_at).map((p) => p.terms.due_at!).sort()[0] ?? null;
        const due = fields.due_at ?? promiseDue;
        return { ...fields, promise_due_at: promiseDue, workflow, issue_type: null, unread_count: 0, message_watermark: 0,
          overdue: !!due && new Date(due).getTime() < Date.now() && workflow !== "resolved",
          next_actor: workflow === "resolved" ? "none" : workflow === "waiting_on_customer" ? "customer" : "merchant",
          next_action: workflow === "resolved" ? "The agreed remedy has been completed." : workflow === "waiting_on_customer"
            ? "Follow up with the customer when they reply." : needsApproval ? "Approve the remaining refund." : "Review the case and share the next update." } satisfies Operations;
      }
      if (action === "timeline") return timeline;
      if (action === "evidence-bundle") return { case: item, timeline, refund_attachments: [] };
      if (action === "promises" && !child) {
        const terms = data as unknown as Terms;
        if (terms.target.kind === "refund" && !item.refund_case_id) throw new ApiError(409, "Link a refund case before recording a refund promise.");
        if (terms.target.kind === "refund" && item.promises.some((p) => p.terms.target.kind === "refund")) throw new ApiError(409, "This case already has a refund promise.");
        const entry = promise(uuid(), terms, "waiting", "This promise is waiting for evidence.", { created_at: now(), updated_at: now() });
        item.promises.push(entry);
        this.recalculate(item);
        this.addEvent(id, "promise_recorded", "merchant_recorded", { promise: terms.promise }, entry);
        return entry;
      }
      const entry = item.promises.find((p) => p.id === child);
      if (!entry) throw new ApiError(404, "Promise not found.");
      if (data.expected_revision !== entry.revision) throw new ApiError(409, "This promise has a newer revision. Reload the case.");
      if (method === "PUT") {
        if (id === demoPrimary && entry.terms.target.kind === "refund") throw new ApiError(409, "Keep the sample refund unchanged for the guided demo. Create your own case to try revisions.");
        const terms = { ...data };
        delete terms.expected_revision;
        entry.terms = terms as unknown as Terms;
        entry.revision += 1;
        entry.updated_at = now();
        entry.outcome = "waiting";
        entry.evidence_source = "merchant_recorded";
        entry.checked_at = null;
        entry.provider_proofs = [];
        this.addEvent(id, "promise_revised", "merchant_recorded", { promise: entry.terms.promise }, entry);
        if (id === demoPrimary) this.invalidate();
      } else if (subaction === "evidence") {
        if (data.finding !== "note") {
          entry.outcome = data.finding === "confirmed" ? "fulfilled" : "needs_review";
          entry.evidence_source = "merchant_recorded";
          entry.checked_at = now();
          entry.reason = data.finding === "confirmed" ? "Internal return milestone confirmed by the merchant." : "The merchant could not confirm the return milestone.";
          if (id === demoPrimary) this.invalidate();
        }
        this.addEvent(id, "merchant_evidence", "merchant_recorded", { note: data.note }, entry);
      } else if (subaction === "refresh") {
        if (!entry.provider_proofs.length) throw new ApiError(409, "This demo record has no provider evidence. Connect an account to check actual records.");
        entry.checked_at = now();
        this.addEvent(id, "provider_observation", "provider_confirmed", { note: "The simulated provider evidence was checked again." }, entry);
      }
      this.recalculate(item);
      return entry;
    }
    throw new ApiError(404, "This action is not available in the demo.");
  }
  request: Requester = async <T>(path: string, method = "GET", input?: unknown) =>
    structuredClone(this.requestResult(path, method, input)) as T;
}
