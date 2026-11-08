"use client";

import { useCallback, useEffect, useState } from "react";
import type { Requester } from "@/lib/domain";
import { Button, Notice } from "./ui";

type Investigation = {
  id: string; case_revision: number; state: string; stale: boolean;
  result: null | {
    status: string; reason: string; next_step: string; evidence_snapshot: string;
    last_verified_at: string | null; evidence_fresh_until: string | null;
    findings: { evidence_id: string; source: string; kind: string; status: string; amount?: string | null; currency?: string | null; verified_at?: string | null }[];
    contradictions: string[]; missing_evidence: string[]; validation_failures: string[];
  };
  review: null | { decision: string; reviewed_at: string; reviewer_merchant_id: string; authorizes_payment: false };
};
const label = (value: string) => value.replaceAll("_", " ");

export function InvestigationReviewPanel({ caseId, request }: { caseId: string; request: Requester }) {
  const [items, setItems] = useState<Investigation[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    const page = await request<{ items: Investigation[] }>(`/resolution-cases/${caseId}/investigations`);
    setItems(page.items); setError(""); setLoading(false);
  }, [caseId, request]);
  useEffect(() => {
    let active = true;
    const refresh = () => request<{ items: Investigation[] }>(`/resolution-cases/${caseId}/investigations`)
      .then((page) => { if (active) { setItems(page.items); setError(""); setLoading(false); } })
      .catch(() => { if (active) { setError("Investigation details are unavailable. Refresh to try again."); setLoading(false); } });
    setItems([]); setLoading(true); void refresh();
    const timer = setInterval(() => void refresh(), 15000);
    return () => { active = false; clearInterval(timer); };
  }, [caseId, request]);
  async function decide(item: Investigation, decision: "approve" | "reject" | "request_evidence") {
    if (!item.result) return;
    setBusy(true); setError("");
    try {
      await request(`/resolution-cases/${caseId}/investigations/${item.id}/review`, "POST", {
        expected_revision: item.case_revision, evidence_snapshot: item.result.evidence_snapshot, decision,
      });
      await load();
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Review could not be saved."); await load().catch(() => {}); }
    finally { setBusy(false); }
  }
  const item = items.find((entry) => entry.result);
  return <section className="section-card investigation-panel" aria-label="Automatic investigation">
    <div className="section-head"><div><div className="eyebrow">PRIVATE MERCHANT REVIEW</div><h2>Automatic investigation</h2></div>
      <Button disabled={busy} onClick={() => void load().catch(() => setError("Investigation details are unavailable."))}>Refresh investigation</Button></div>
    <p>Reviewing an investigation records your decision. Payment requires the separate refund approval and execution workflow.</p>
    {error && <Notice>{error}</Notice>}
    {loading && <p role="status">Loading investigation…</p>}
    {items[0] && !items[0].result && <p role="status">Revision {items[0].case_revision}: {label(items[0].state)}. The investigation worker processes this automatically.</p>}
    {!loading && !items.length && <p>No investigation is available yet.</p>}
    {item?.result && <article>
      <h3>{label(item.result.status)} · revision {item.case_revision} · {item.state}</h3>
      {item.stale && <Notice>This result is stale. Wait for the current investigation before approving.</Notice>}
      <p>{item.result.reason}</p><p><strong>Proposed next step:</strong> {label(item.result.next_step)}</p>
      <p>Last verified: {item.result.last_verified_at ? new Date(item.result.last_verified_at).toLocaleString() : "Never verified"}</p>
      <ul>{item.result.findings.map((finding) => <li key={finding.evidence_id}>
        <strong>{label(finding.source)}:</strong> {label(finding.kind)} · {finding.status}
        {finding.amount && ` · ${finding.amount} ${finding.currency ?? ""}`}
        {finding.verified_at && ` · verified ${new Date(finding.verified_at).toLocaleString()}`}
        <br /><small>Evidence {finding.evidence_id}</small>
      </li>)}</ul>
      {!!item.result.contradictions.length && <p><strong>Contradictions:</strong> {item.result.contradictions.map(label).join(", ")}</p>}
      {!!item.result.missing_evidence.length && <p><strong>Missing evidence:</strong> {item.result.missing_evidence.map(label).join(", ")}</p>}
      {!!item.result.validation_failures.length && <p><strong>Investigation limits:</strong> {item.result.validation_failures.map(label).join(", ")}</p>}
      {item.review ? <p role="status">Review: {label(item.review.decision)} · {new Date(item.review.reviewed_at).toLocaleString()} · reviewer {item.review.reviewer_merchant_id}. No payment authorized.</p>
        : <div className="review-actions">
          <Button disabled={busy || item.stale} onClick={() => void decide(item, "approve")}>Approve investigation</Button>
          <Button disabled={busy || item.case_revision !== items[0]?.case_revision} onClick={() => void decide(item, "reject")}>Reject investigation</Button>
          <Button disabled={busy || item.case_revision !== items[0]?.case_revision} onClick={() => void decide(item, "request_evidence")}>Request more evidence</Button>
        </div>}
    </article>}
    {items.filter((entry) => entry.result && entry.id !== item?.id).map((entry) => <details key={entry.id}><summary>Earlier revision {entry.case_revision} · {entry.state}{entry.review ? ` · ${label(entry.review.decision)}` : ""}</summary><p>{entry.result?.reason}</p></details>)}
  </section>;
}
