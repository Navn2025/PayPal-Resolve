"use client";
import { BuyerAssurance, ReturnGuidePanel } from "./assurance";
import { useEffect, useState } from "react";
import { buyerAction, failureText, type ReturnCatalog } from "@/lib/platform";
import { ReturnProgress, ReturnRequestForm, type PublicReturnPolicy } from "./return-workflow";
import { Button, Notice } from "./ui";
import { money } from "@/lib/domain";

type Choice = Offer["choices"][number];
const kindTitles: Record<string, string> = {
  return: "Return your item", replacement: "Replacement", store_credit_or_exchange: "Store credit or exchange",
  order_cancellation: "Order cancellation", subscription: "Subscription change", billing_correction: "Billing correction",
  dispute_handoff: "Dispute review",
};
const mentionsReturn = (choice: Choice) => /\breturn/i.test(choice.promise);
/** The remedy in plain words, from its kind and the merchant's wording. */
function choiceTitle(choice: Choice) {
  if (choice.kind !== "refund") return kindTitles[choice.kind] ?? choice.kind.replaceAll("_", " ");
  if (choice.conditions_required && mentionsReturn(choice)) return "Refund after return";
  return /\bpartial\b/i.test(choice.promise) ? "Partial refund" : "Refund";
}
/** One muted line: when the remedy applies, or the merchant's own description when it has no conditions. */
function choiceNote(choice: Choice) {
  if (!choice.conditions_required) return choice.promise;
  return mentionsReturn(choice) ? "You'll get this once your return arrives." : "You'll get this once the required steps are completed.";
}

interface Offer { id: string; revision: number; status: string; stale: boolean; expires_at: string; selected_choice: string | null; choices: { id: string; promise: string; kind: string; amount?: string | null; currency?: string | null; conditions_required: boolean }[] }

export function BuyerResolution({ token }: { token: string }) {
  const [offers, setOffers] = useState<Offer[]>([]); const [catalog, setCatalog] = useState<ReturnCatalog | null>(null);
  const [policy, setPolicy] = useState<PublicReturnPolicy>();
  const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  async function load() {
    const [o, r, p] = await Promise.all([buyerAction<{ items: Offer[] }>("offers", token), buyerAction<ReturnCatalog>("returns", token), buyerAction<PublicReturnPolicy>("return-policy", token)]);
    setOffers(o.items); setCatalog(r); setPolicy(p);
  }
  useEffect(() => { let active = true;
    Promise.all([buyerAction<{ items: Offer[] }>("offers", token), buyerAction<ReturnCatalog>("returns", token), buyerAction<PublicReturnPolicy>("return-policy", token)]).then(([o, r, p]) => { if (active) { setOffers(o.items); setCatalog(r); setPolicy(p); } }).catch(f => { if (active) setError(failureText(f)); });
    return () => { active = false; };
  }, [token]);
  async function decide(offer: Offer, decision: string, choiceId?: string) {
    setBusy(true); setError("");
    try { await buyerAction("decision", token, { offer_id: offer.id, expected_revision: offer.revision, decision, choice_id: choiceId ?? null }); await load(); }
    catch (failure) { setError(failureText(failure)); } finally { setBusy(false); }
  }
  return <>
    <BuyerAssurance token={token}/>
    {error && <Notice>{error}</Notice>}
    {offers.map(offer => {
      const open = offer.status === "published" && !offer.stale;
      const single = offer.choices.length === 1;
      const decline = <Button disabled={busy} onClick={() => void decide(offer, "decline")}>Decline offer</Button>;
      return <section className="section-card offer-card" key={offer.id}><div className="eyebrow">YOUR CHOICE</div><h3>Resolution offer</h3>
        {open ? <p className="offer-intro">Choose the remedy you agree to. Offer expires {new Date(offer.expires_at).toLocaleDateString()}.</p>
          : <Notice tone={offer.status === "accepted" ? "success" : "info"}>{offer.status === "accepted" ? "Your acceptance has been recorded. Any prerequisite conditions still apply; payment is processed separately." : offer.status === "declined" ? "You declined this offer. The merchant can prepare another one." : "These terms changed or expired. Ask the merchant for an updated offer."}</Notice>}
        <ul className="offer-choices">{offer.choices.map(choice => {
          const chosen = offer.selected_choice === choice.id;
          return <li key={choice.id} className={`offer-choice ${chosen ? "offer-chosen" : ""}`}>
            <div className="offer-choice-head"><strong>{choiceTitle(choice)}</strong>
              {choice.amount && <span className="offer-amount">{money(choice.amount, choice.currency ?? "USD")}</span>}</div>
            <p className="offer-note">{choiceNote(choice)}</p>
            {chosen && <span className="badge badge-fulfilled offer-status"><span />Accepted</span>}
            {open && <div className="offer-actions">
              <Button variant="primary" disabled={busy} onClick={() => void decide(offer, "accept", choice.id)}>Accept this option</Button>
              {single && decline}</div>}
          </li>;
        })}</ul>
        {open && !single && <div className="offer-actions offer-decline"><span>None of these work for you?</span>{decline}</div>}
      </section>;
    })}
    {catalog && (catalog.orders.length > 0 || catalog.items.length > 0) && <section className="section-card"><div className="eyebrow">RETURNS & REPLACEMENTS</div><h3>Your items</h3>
      {catalog.items.map(item => <div key={item.id}><ReturnProgress item={item}/><ReturnGuidePanel item={item} token={token}/></div>)}
      <details><summary>Request an item return</summary><ReturnRequestForm policy={policy} catalog={catalog} submit={body => buyerAction("returns/request", token, body)} done={() => void load().catch(f => setError(failureText(f)))} /></details>
    </section>}
  </>;
}
