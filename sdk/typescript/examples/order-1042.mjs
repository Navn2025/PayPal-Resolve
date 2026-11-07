import { ResolveClient } from "@resolve-paypal/sdk";

const { RESOLVE_API_URL, RESOLVE_API_KEY, PAYPAL_CAPTURE_ID, PAYPAL_ORDER_ID, RESOLVE_EXTERNAL_REFERENCE = "ORDER-1042" } = process.env;
if (!RESOLVE_API_URL || !RESOLVE_API_KEY || !PAYPAL_CAPTURE_ID) {
  throw new Error("Set RESOLVE_API_URL, RESOLVE_API_KEY, and PAYPAL_CAPTURE_ID on your server.");
}

const resolve = new ResolveClient({ baseUrl: RESOLVE_API_URL, apiKey: RESOLVE_API_KEY, timeoutMs: 30_000 });
const caseRecord = await resolve.upsertCase({
  external_reference: RESOLVE_EXTERNAL_REFERENCE,
  order_reference: RESOLVE_EXTERNAL_REFERENCE,
  title: "Buyer refund inquiry",
});
await resolve.linkRecord(caseRecord.id, { kind: "paypal_capture", reference: PAYPAL_CAPTURE_ID });
if (PAYPAL_ORDER_ID) {
  await resolve.linkRecord(caseRecord.id, { kind: "paypal_order", reference: PAYPAL_ORDER_ID });
}
await resolve.addEvidence(caseRecord.id, {
  source: "store-support",
  source_event_id: "refund-approval-example",
  evidence_type: "refund_approved",
  occurred_at: "2026-11-07T11:00:00Z",
  summary: "Support recorded an approval to refund USD 25.",
  amount: "25.00",
  currency: "USD",
});

const before = await resolve.getCase(caseRecord.id);
const refresh = await resolve.refreshEvidence(caseRecord.id);
const timeline = await resolve.getTimeline(caseRecord.id);
const bundle = await resolve.getEvidenceBundle(caseRecord.id);
// Print a summary only. Keep the full timeline, evidence and any buyer link private.
console.log(JSON.stringify({
  caseId: caseRecord.id,
  issuesBefore: before.evidence_summary?.issues.map(({ kind, status }) => ({ kind, status })),
  checkedAt: refresh.checked_at,
  verified: refresh.verified.map(({ kind, status, amount, currency }) => ({ kind, status, amount, currency })),
  linkedRecords: bundle.linked_records.length,
  events: timeline.total,
  refundStatus: bundle.case.evidence_summary?.refund_status,
  issuesAfter: bundle.case.evidence_summary?.issues.map(({ kind, status }) => ({ kind, status })),
}, null, 2));
