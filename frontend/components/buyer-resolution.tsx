"use client";
import { BuyerAssurance, ReturnGuidePanel } from "./assurance";
import { useEffect, useState } from "react";
import { buyerAction, failureText, type ReturnCatalog } from "@/lib/platform";
import { ReturnProgress, ReturnRequestForm, type PublicReturnPolicy } from "./return-workflow";
import { Button, Notice } from "./ui";

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
    {offers.map(offer => <section className="section-card" key={offer.id}><div className="eyebrow">YOUR CHOICE</div><h3>Resolution offer</h3>
      <p>{offer.status === "accepted" ? "Your acceptance has been recorded. Any prerequisite conditions still apply; payment is processed separately." : offer.status === "declined" ? "You declined this offer. The merchant can prepare another one." : offer.stale ? "These terms changed or expired. Ask the merchant for an updated offer." : `Choose the remedy you agree to. Offer expires ${new Date(offer.expires_at).toLocaleDateString()}.`}</p>
      {offer.choices.map(choice => <div className="ops-record" key={choice.id}><strong>{choice.kind.replaceAll("_", " ")}{choice.amount ? ` · ${choice.currency ?? "USD"} ${choice.amount}` : ""}</strong><p>{choice.promise}</p>
        {choice.conditions_required && <small>Prerequisite conditions must also be completed.</small>}
        {offer.status === "published" && !offer.stale && <Button variant="primary" disabled={busy} onClick={() => void decide(offer, "accept", choice.id)}>Accept this option</Button>}
        {offer.selected_choice === choice.id && <strong>Accepted option</strong>}
      </div>)}
      {offer.status === "published" && !offer.stale && <Button disabled={busy} onClick={() => void decide(offer, "decline")}>Decline offer</Button>}
    </section>)}
    {catalog && (catalog.orders.length > 0 || catalog.items.length > 0) && <section className="section-card"><div className="eyebrow">RETURNS & REPLACEMENTS</div><h3>Your items</h3>
      {catalog.items.map(item => <div key={item.id}><ReturnProgress item={item}/><ReturnGuidePanel item={item} token={token}/></div>)}
      <details><summary>Request an item return</summary><ReturnRequestForm policy={policy} catalog={catalog} submit={body => buyerAction("returns/request", token, body)} done={() => void load().catch(f => setError(failureText(f)))} /></details>
    </section>}
  </>;
}
