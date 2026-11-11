"use client";

import { useState, type FormEvent } from "react";
import { money, type LegacyCase, type Requester } from "@/lib/domain";
import { Button, Modal, Notice } from "./ui";

/**
 * Sets the agreed refund amount on the linked payment case through the existing
 * PUT /cases/{id}/commitment. The backend validates the amount, the capture limit and the
 * state fingerprint exactly as before; this form only collects the merchant's entry.
 */
export function AgreementForm({ payment, fingerprint, request, onClose, onSaved }: {
  payment: LegacyCase; fingerprint: string; request: Requester; onClose: () => void; onSaved: () => void;
}) {
  const current = payment.commitment;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    const condition = String(values.get("condition") ?? "").trim();
    setBusy(true); setError("");
    try {
      await request(`/cases/${payment.id}/commitment`, "PUT", {
        state_fingerprint: fingerprint,
        commitment: {
          amount: String(values.get("amount") ?? "").trim(), currency: "USD",
          source_message: String(values.get("source") ?? "").trim(),
          condition: condition || null,
          status: values.has("accepted") ? "accepted" : "proposed",
        },
      });
      onSaved();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not save the agreed amount. Try again.");
    } finally { setBusy(false); }
  }
  return <Modal title="Set agreed amount" onClose={onClose} busy={busy}
    description={`The refund amount agreed with the buyer for order ${payment.order_id}. Captured: ${money(payment.payment.captured_amount)}.`}>
    <form className="triage-form" onSubmit={save}>
      {error && <Notice>{error}</Notice>}
      <label className="field"><span>Agreed refund amount (USD)</span>
        <input name="amount" inputMode="decimal" required pattern="[0-9]{1,10}(\.[0-9]{1,2})?" placeholder="40.00"
          defaultValue={current?.amount ?? ""} /></label>
      <label className="field"><span>Where it was agreed</span>
        <textarea name="source" required maxLength={5000} rows={3} placeholder="For example: support chat on Nov 7, message from the merchant"
          defaultValue={current?.source_message ?? ""} /></label>
      <label className="field"><span>Condition (optional)</span>
        <input name="condition" maxLength={500} placeholder="For example: after the return arrives"
          defaultValue={current?.condition ?? ""} /></label>
      <label className="customer-checkbox"><input type="checkbox" name="accepted" defaultChecked={current?.status !== "proposed"} /> The buyer accepted this amount.</label>
      <Button type="submit" variant="primary" disabled={busy}>{busy ? "Saving…" : "Save agreed amount"}</Button>
      <p className="card-note">This records the agreement only. It does not approve or send a refund.</p>
    </form>
  </Modal>;
}
