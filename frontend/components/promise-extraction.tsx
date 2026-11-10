"use client";

import { useState } from "react";
import { money, pretty, remedyLabels, type Remedy, type Requester } from "@/lib/domain";
import type { PromiseDraft } from "./forms";
import { Button, Notice } from "./ui";

type Proposal = {
  kind: Remedy; amount_cents: number | null; action: string | null; condition: string | null; deadline: string | null;
  source_message_id: string; exact_quote: string; confidence: number; needs_review: boolean;
  supporting_message_ids: string[]; possible_revision: boolean;
};
type Dropped = { reason: string; detail: string; kind: string | null; source_message_id: string | null; exact_quote: string | null };
type Extraction = {
  status: "ok" | "needs_review"; review_reasons: string[]; proposals: Proposal[]; dropped: Dropped[];
  tokens: number; cache_hit: boolean; skipped_reason: string | null;
  flags?: { rule_id: string; label: string; message_id: string }[];
};

const reviewText: Record<string, string> = {
  extraction_disabled: "AI extraction is turned off on this server.",
  budget_exceeded: "Today's AI budget is used up. Try again tomorrow, or record the promise yourself.",
  data_policy_blocked: "This server's data policy does not allow sending conversations to the AI provider.",
  not_configured: "AI extraction is not set up on this server.",
  no_messages: "This case has no conversation to read yet.",
  auth_error: "The AI provider did not accept this server's credentials.",
  model_not_found: "The AI model configured on this server is not available.",
  rate_limited: "The AI provider is busy. Try again in a minute.",
  bad_request: "The AI provider could not read this conversation.",
  timeout: "The AI provider took too long to answer. Try again.",
  connection_error: "Could not reach the AI provider. Try again.",
  provider_error: "The AI provider had a problem. Try again later.",
  unexpected_error: "Something went wrong while reading the conversation.",
  invalid_json: "The AI answer could not be read, so nothing was suggested from it.",
  schema_invalid: "Part of the AI answer was not in the expected format.",
  low_confidence: "Some suggestions are uncertain. Check them carefully.",
};
const droppedText: Record<string, string> = {
  buyer_message: "It came from a buyer message. Only merchant messages can create promises.",
  quote_not_found: "The quoted words are not in the message it cited.",
  amount_not_in_quote: "The amount is not written in the quoted words.",
  amount_not_allowed: "Amounts are only taken for refunds.",
  unknown_kind: "It is not a supported promise type.",
  unknown_message: "It cited a message that is not in this conversation.",
  duplicate: "It repeated an earlier suggestion.",
  schema_invalid: "It was not in the expected format.",
  limit_exceeded: "There were too many suggestions in one answer.",
};
const plain = (texts: Record<string, string>, reason: string) => texts[reason] ?? pretty(reason) + ".";

export function draftFrom(proposal: Proposal): PromiseDraft {
  const notes = [`Suggested from merchant message ${proposal.source_message_id}: "${proposal.exact_quote}"`];
  if (proposal.condition) notes.push(`Condition: ${proposal.condition}`);
  if (proposal.deadline) notes.push(`Deadline: ${proposal.deadline}`);
  if (proposal.supporting_message_ids.length) notes.push(`Restated in ${proposal.supporting_message_ids.join(", ")}`);
  return {
    kind: proposal.kind, action: proposal.action ?? undefined,
    amount: proposal.kind === "refund" && proposal.amount_cents ? (proposal.amount_cents / 100).toFixed(2) : undefined,
    promise: proposal.exact_quote, source_note: notes.join(". "), source_reference: `Chat message ${proposal.source_message_id}`,
  };
}

export function PromiseExtractionPanel({ caseId, request, onUse }: {
  caseId: string; request: Requester; onUse: (draft: PromiseDraft) => void;
}) {
  const [result, setResult] = useState<Extraction | null>(null);
  const [dismissed, setDismissed] = useState<number[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function extract() {
    setBusy(true); setError("");
    try {
      setResult(await request<Extraction>(`/resolution-cases/${caseId}/ai/extract-promises`, "POST"));
      setDismissed([]);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Suggestions are unavailable. Try again."); }
    finally { setBusy(false); }
  }
  const visible = result?.proposals.map((proposal, index) => ({ proposal, index })).filter(({ index }) => !dismissed.includes(index)) ?? [];
  return <section className="ai-card extraction-panel" aria-label="Promise suggestions" aria-busy={busy}>
    <header className="card-head"><div><div className="eyebrow">AI SUGGESTIONS</div><h3>Promise suggestions</h3></div>
      <Button disabled={busy} onClick={() => void extract()}>{busy ? "Reading conversation…" : "Extract promises from conversation"}</Button></header>
    <p className="card-note">Suggestions only. Nothing is saved or paid until you confirm.</p>
    {!result && !error && <p className="panel-state">{busy ? "Reading the stored conversation…" : "No suggestions yet. Extract to read the stored conversation."}</p>}
    {error && <Notice>{error}</Notice>}
    {result && <p className="card-note" role="status">
      {result.cache_hit ? "cached, 0 tokens" : result.skipped_reason ? "No AI call made" : `${result.tokens} tokens`}
      {" · "}{result.proposals.length} {result.proposals.length === 1 ? "suggestion" : "suggestions"}</p>}
    {!!result?.flags?.length && <div className="injection-flags" role="note" aria-label="Suspicious buyer instructions">
      <span className="badge badge-needs_review">Suspicious instruction ignored</span>
      <p className="muted">A buyer message tried to give instructions. It was read as ordinary chat and cannot create a promise.</p>
      <ul>{result.flags.map((flag, index) => <li key={index}>
        <strong>{flag.rule_id}</strong> · {flag.label} · buyer message {flag.message_id}</li>)}</ul>
    </div>}
    {result?.skipped_reason === "no_merchant_messages" && <p className="panel-state">No merchant messages yet, so there is nothing to suggest.</p>}
    {!!result?.review_reasons.length && <Notice><strong>Needs your review:</strong> {result.review_reasons.map((reason) => plain(reviewText, reason)).join(" ")}</Notice>}
    {result && !result.proposals.length && !result.review_reasons.length && !result.skipped_reason && <p className="panel-state">No promises were found in this conversation.</p>}
    <div className="proposal-list">{visible.map(({ proposal, index }) => <article className="proposal-card" key={index}
      aria-label={`Suggested ${remedyLabels[proposal.kind] ?? pretty(proposal.kind)}`}>
      <div className="proposal-head"><h4>{remedyLabels[proposal.kind] ?? pretty(proposal.kind)}</h4>
        <span className="proposal-badges">
          {proposal.possible_revision && <span className="badge badge-needs_review">Possible revision</span>}
          {!!proposal.supporting_message_ids.length && <span className="badge badge-pending">Also in {proposal.supporting_message_ids.join(", ")}</span>}
          {proposal.needs_review && <span className="badge badge-needs_review">Low confidence</span>}
        </span></div>
      <dl className="proposal-terms">
        {proposal.amount_cents !== null && <><dt>Amount</dt><dd className="money-value">{money(proposal.amount_cents / 100)}</dd></>}
        {proposal.action && <><dt>Action</dt><dd>{pretty(proposal.action)}</dd></>}
        {proposal.condition && <><dt>Condition</dt><dd>{proposal.condition}</dd></>}
        {proposal.deadline && <><dt>Deadline</dt><dd>{proposal.deadline}</dd></>}
      </dl>
      <blockquote className="proposal-quote"><mark>{proposal.exact_quote}</mark>
        <footer>Merchant message {proposal.source_message_id}</footer></blockquote>
      <div className="card-actions">
        <Button variant="primary" onClick={() => onUse(draftFrom(proposal))}>Use this proposal</Button>
        <Button onClick={() => setDismissed((previous) => [...previous, index])}>Dismiss</Button>
      </div>
    </article>)}</div>
    {!!result?.dropped.length && <details className="proposal-dropped"><summary>{result.dropped.length} not suggested</summary>
      <ul>{result.dropped.map((item, index) => <li key={index}>
        {item.exact_quote && <q>{item.exact_quote}</q>} {plain(droppedText, item.reason)}
        {item.source_message_id && <small> (message {item.source_message_id})</small>}
      </li>)}</ul></details>}
  </section>;
}
