"use client";

import { useEffect, useState } from "react";
import { Copy, Sparkles } from "lucide-react";
import { money, type Requester } from "@/lib/domain";
import { readJson } from "@/lib/http";
import { Button, Notice } from "./ui";

type OptionId = "refund_after_return" | "partial_refund";
type Option = { id: OptionId; title: string; description: string; amount: string; currency: string; requires_return: boolean; reason: string };
type Suggestions = {
  facts: { payment_linked: boolean; captured_amount: string | null; completed_refund_amount: string | null;
    pending_refund_amount: string | null; refundable_amount: string | null; currency: string };
  options: Option[]; unavailable: { kind: string; reason: string }[];
};
type Ranking = {
  source: "ai" | "code"; label: string | null; fallback_reason: string | null; issue: string; buyer_preference: string;
  ranking: { option_id: OptionId; reason: string }[]; buyer_message: string;
};
type Created = { option_id: OptionId; promises: { id: string }[]; offer_choice: { promise_id: string; expected_revision: number } };

const fallbackText: Record<string, string> = {
  extraction_disabled: "AI is turned off on this server", not_configured: "AI is not set up on this server",
  data_policy_blocked: "the data policy does not allow the AI provider", budget_exceeded: "today's AI budget is used up",
  fact_guard: "the AI mentioned an option or amount that is not listed", invalid_json: "the AI answer could not be read",
  no_messages: "there is no conversation to read yet", no_options: "there are no options to rank",
};
const kindText: Record<string, string> = {
  refund_after_return: "Refund after return", partial_refund: "Partial refund", store_credit: "Store credit", replacement: "Replacement",
};
const words = (value: string) => value.replace(/_/g, " ");
// A week from now, in the viewer's local time, for the offer expiry field.
const inAWeek = () => { const at = new Date(Date.now() + 7 * 864e5); at.setSeconds(0, 0);
  return new Date(at.getTime() - at.getTimezoneOffset() * 6e4).toISOString().slice(0, 16); };

/** Code-built remedy options, an optional AI ranking, then two separate merchant steps: create promises, publish the offer. */
export function SuggestedRemedies({ caseId, request, onCreated }: { caseId: string; request: Requester; onCreated: () => void }) {
  const [data, setData] = useState<Suggestions | null>(null);
  const [ranking, setRanking] = useState<Ranking | null>(null);
  const [chosen, setChosen] = useState<OptionId | null>(null);
  const [created, setCreated] = useState<Created | null>(null);
  const [expiry, setExpiry] = useState(inAWeek);
  const [published, setPublished] = useState<number | null>(null);
  const [busy, setBusy] = useState<"rank" | "create" | "publish" | null>(null);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let active = true;
    request<Suggestions>(`/resolution-cases/${caseId}/remedies`)
      .then((value) => { if (active) { setData(value); setChosen(value.options[0]?.id ?? null); } })
      .catch((failure) => { if (active) setError(failure instanceof Error ? failure.message : "Suggestions are unavailable."); });
    return () => { active = false; };
  }, [caseId, request]);

  async function run<T>(step: "rank" | "create" | "publish", action: () => Promise<T>) {
    setBusy(step); setError("");
    try { return await action(); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "The action could not be completed."); }
    finally { setBusy(null); }
  }
  const rank = () => run("rank", async () => {
    const value = await request<Ranking>(`/resolution-cases/${caseId}/ai/rank-remedies`, "POST");
    setRanking(value);
    if (value.ranking[0]) setChosen(value.ranking[0].option_id);
  });
  const create = () => run("create", async () => {
    const option = data?.options.find((item) => item.id === chosen);
    if (!option) return;
    setCreated(await request<Created>(`/resolution-cases/${caseId}/remedies/promises`, "POST",
      { option_id: option.id, expected_amount: option.amount }));
    onCreated();
  });
  // The existing buyer-offer endpoint; the backend re-checks the refundable balance. Never called automatically.
  const publish = () => run("publish", async () => {
    if (!created) return;
    const offer = await readJson<{ revision: number }>(await fetch(`/api/platform/cases/${caseId}/offers`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ choices: [created.offer_choice], expires_at: new Date(expiry).toISOString() }),
    }));
    setPublished(offer.revision);
  });

  const order = ranking ? ranking.ranking.map((item) => item.option_id) : data?.options.map((item) => item.id) ?? [];
  const options = order.map((id) => data?.options.find((item) => item.id === id)).filter((item): item is Option => !!item);
  const reasonFor = (option: Option) => ranking?.ranking.find((item) => item.option_id === option.id)?.reason ?? option.reason;
  const facts = data?.facts;
  const unavailable = data?.unavailable.filter((item) => !data.options.some((option) => option.id === item.kind)) ?? [];

  return <section className="section-card remedies-panel" aria-label="Suggested remedies" aria-busy={!data && !error}>
    <div className="section-head"><div><div className="eyebrow">From the payment and return policy</div><h3>Suggested remedies</h3></div>
      {!!data?.options.length && !created && <Button className="small-button" disabled={!!busy} onClick={() => void rank()}>
        <Sparkles size={14} /> {busy === "rank" ? "Ranking…" : "Rank with AI"}</Button>}</div>
    {!data && !error && <p className="panel-state" role="status">Checking which remedies fit…</p>}
    {error && <Notice>{error}</Notice>}
    {facts?.refundable_amount && <p className="card-note remedy-balance">
      Refundable {money(facts.refundable_amount, facts.currency)} = {money(facts.captured_amount, facts.currency)} captured
      − {money(facts.completed_refund_amount, facts.currency)} refunded − {money(facts.pending_refund_amount, facts.currency)} pending.</p>}
    {ranking?.source === "ai" && <p className="remedy-ai"><span className="badge badge-needs_review ai-label"><span />{ranking.label}</span>
      <span>Issue: {words(ranking.issue)} · Buyer prefers: {words(ranking.buyer_preference)}</span></p>}
    {ranking?.source === "code" && <p className="card-note">Code order shown. AI ranking not used: {fallbackText[ranking.fallback_reason ?? ""] ?? words(ranking.fallback_reason ?? "")}.</p>}
    {data && !data.options.length && !created && <p className="panel-state">No remedy to suggest: {data.unavailable[0]?.reason}</p>}
    {!!options.length && !created && <fieldset className="remedy-list" disabled={!!busy}>
      <legend className="sr-only">Choose one remedy</legend>
      {options.map((option, index) => <label key={option.id} className={`remedy-option ${chosen === option.id ? "remedy-chosen" : ""}`}>
        <input type="radio" name={`remedy-${caseId}`} checked={chosen === option.id} onChange={() => setChosen(option.id)} />
        <span className="remedy-body">
          <span className="remedy-title"><strong>{ranking ? `${index + 1}. ` : ""}{option.title}</strong>
            <span className="money-value">{money(option.amount, option.currency)}</span></span>
          <span className="remedy-text">{option.description}</span>
          <span className="card-note">{reasonFor(option)}</span>
        </span>
      </label>)}
    </fieldset>}
    {ranking?.buyer_message && !created && <div className="remedy-message">
      <div className="code-head"><h4>Draft message to the buyer</h4>
        <Button className="small-button" aria-label="Copy buyer message" onClick={() => {
          void navigator.clipboard.writeText(ranking.buyer_message).then(() => setCopied(true), () => setCopied(false)); }}>
          <Copy size={14} /> {copied ? "Copied" : "Copy"}</Button></div>
      <p>{ranking.buyer_message}</p></div>}
    {!!options.length && !created && <div className="card-actions">
      <Button variant="primary" disabled={!chosen || !!busy} onClick={() => void create()}>{busy === "create" ? "Creating…" : "Create promises"}</Button>
      <small>Records the promise for the chosen remedy. Nothing is sent to the buyer or refunded.</small></div>}
    {created && <div className="remedy-created">
      <Notice tone="success">Promises created for {kindText[created.option_id].toLowerCase()}. Review them in Promises &amp; evidence.</Notice>
      {published === null ? <div className="remedy-publish">
        <label className="field"><span>Offer expires</span>
          <input type="datetime-local" value={expiry} onChange={(event) => setExpiry(event.target.value)} /></label>
        <div className="card-actions">
          <Button disabled={!!busy || !expiry} onClick={() => void publish()}>{busy === "publish" ? "Publishing…" : "Publish offer"}</Button>
          <small>Shows this choice to the buyer in the customer portal. The refundable balance is checked again first.</small></div>
      </div> : <Notice tone="success">Offer {published} published to the buyer.</Notice>}
    </div>}
    {!!unavailable.length && <details className="remedy-unavailable"><summary>Not offered ({unavailable.length})</summary>
      <ul>{unavailable.map((item) => <li key={item.kind}><strong>{kindText[item.kind] ?? words(item.kind)}:</strong> {item.reason}</li>)}</ul>
    </details>}
    <p className="advisory">Suggestions only. You confirm every step; publishing never happens automatically.</p>
  </section>;
}
