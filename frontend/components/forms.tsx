"use client";
import Link from "next/link";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { ArrowRight, KeyRound, LockKeyhole } from "lucide-react";
import { amountCents, centsText, money, remedyLabels, type Approval, type CaseView, type LegacyCase, type Page, type PromiseView, type Remedy, type Requester, type Target, type Terms } from "@/lib/domain";
import { Button, Modal, Notice } from "./ui";
const message = (error: unknown) => error instanceof Error ? error.message : "Something went wrong. Try again.";
function useSubmission() {
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    async function submit(event: FormEvent<HTMLFormElement>, action: (data: FormData) => Promise<void>) {
        event.preventDefault();
        if (busy)
            return;
        const data = new FormData(event.currentTarget);
        setBusy(true);
        setError("");
        try {
            await action(data);
        }
        catch (failure) {
            setError(message(failure));
        }
        finally {
            setBusy(false);
        }
    }
    return { busy, error, submit };
}
const value = (data: FormData, key: string) => String(data.get(key) ?? "").trim();
const field = (label: string, children: ReactNode, hint?: string) => <label className="field"><span>{label}</span>{children}{hint && <small>{hint}</small>}</label>;
const footer = (onClose: () => void, busy: boolean, label: string) => <div className="modal-footer">
  <Button onClick={onClose} disabled={busy}>Cancel</Button>
  <Button variant="primary" type="submit" disabled={busy}>{busy ? "Saving…" : label}<ArrowRight size={15}/></Button>
</div>;
export function CaseForm({ request, onClose, onSaved }: {
    request: Requester;
    onClose: () => void;
    onSaved: (item: CaseView) => void;
}) {
    const { busy, error, submit } = useSubmission();
    const [mode, setMode] = useState("none");
    const [existing, setExisting] = useState<LegacyCase[]>([]);
    const [lookup, setLookup] = useState("");
    const [createdPayment, setCreatedPayment] = useState<LegacyCase | null>(null);
    useEffect(() => {
        let current = true;
        if (mode === "existing") {
            setLookup("Loading payment cases…");
            request<Page<LegacyCase>>("/cases?limit=100").then((result) => {
                if (current) {
                    setExisting(result.items);
                    setLookup(result.total > 100 ? "Showing the first 100 payment cases." : "");
                }
            }).catch((failure) => {
                if (current)
                    setLookup(message(failure));
            });
        }
        return () => { current = false; };
    }, [mode, request]);
    return <Modal title="Create a resolution case" description="Start with the customer’s issue. You can add promises after saving." onClose={onClose} busy={busy}>
    <form onSubmit={(event) => submit(event, async (data) => {
            const title = value(data, "title"), order = value(data, "order");
            let payment = createdPayment;
            if (mode === "new" && !payment) {
                if (!order)
                    throw new Error("Enter the PayPal order ID for this payment.");
                const amount = value(data, "promise_amount");
                payment = await request<LegacyCase>("/cases", "POST", {
                    order_id: order, complaint: title,
                    payment: { capture_id: value(data, "capture"), captured_amount: value(data, "captured"), currency: "USD" },
                    ...(amount && { commitment: { amount, currency: "USD", status: "accepted", source_message: value(data, "agreement") } }),
                });
                setCreatedPayment(payment);
            }
            const linked = payment?.id ?? (mode === "existing" ? value(data, "legacy_id") || value(data, "legacy_manual") : "");
            if (mode === "existing" && !linked)
                throw new Error("Select a payment case or enter its ID.");
            const item = await request<CaseView>("/resolution-cases", "POST", {
                title, order_reference: order || payment?.order_id || existing.find((entry) => entry.id === linked)?.order_id || null,
                refund_case_id: linked || null,
            });
            onSaved(item);
        })}>
      <div className="modal-body">
        {error && <Notice>{error}</Notice>}
        {field("Case title", <input name="title" placeholder="e.g. Refund for a returned item" required maxLength={160} autoFocus/>)}
        {field(mode === "new" ? "PayPal order ID" : "Order reference (optional)", <input name="order" placeholder="Order reference or PayPal order ID" maxLength={mode === "new" ? 100 : 160} required={mode === "new"}/>)}
        {field("Payment record", <select name="payment_mode" value={mode} onChange={(event) => setMode(event.target.value)} disabled={!!createdPayment}>
          <option value="none">No linked payment</option><option value="existing">Link an existing payment case</option><option value="new">Record a PayPal payment</option>
        </select>)}
        {mode === "existing" && <>{field("Existing payment case", <select name="legacy_id" defaultValue="">
          <option value="">Select a case</option>{existing.map((entry) => <option key={entry.id} value={entry.id}>{entry.order_id} · {entry.complaint}</option>)}
        </select>, lookup || "Only one resolution case can link to a payment case.")}
        {field("Or enter a payment case ID", <input name="legacy_manual" placeholder="Resolve case ID"/>)}</>}
        {mode === "new" && (createdPayment ? <Notice tone="info">Payment record saved. Retry to finish linking it to the new case.</Notice> : <>
          {field("PayPal capture ID", <input name="capture" required maxLength={100}/>)}
          <div className="field-grid">
            {field("Captured amount (USD)", <input name="captured" placeholder="100.00" pattern="[0-9]+(\.[0-9]{1,2})?" inputMode="decimal" required/>)}
            {field("Agreed refund (optional)", <input name="promise_amount" placeholder="30.00" pattern="[0-9]+(\.[0-9]{1,2})?" inputMode="decimal"/>)}
          </div>
          {field("Source of the agreement", <textarea name="agreement" rows={2} placeholder="Required if you entered an agreed refund" maxLength={3000}/>)}
        </>)}
      </div>
      {footer(onClose, busy, "Create case")}
    </form>
  </Modal>;
}
type Spec = {
    key: string;
    label: string;
    hint?: string;
    optional?: boolean;
    options?: [
        string,
        string
    ][];
    money?: boolean;
};
const trackingFields: Spec[] = [
    { key: "tracker_id", label: "EasyPost tracker ID", hint: "trk_…" },
    { key: "tracking_code", label: "Carrier tracking number" }, { key: "carrier", label: "Carrier" },
];
function specs(kind: Remedy, choice: string): Spec[] {
    switch (kind) {
        case "refund": return [{ key: "amount", label: "Agreed refund (USD)", money: true }];
        case "return": return [{ key: "return_reference", label: "Return reference" },
            { key: "milestone", label: "Required milestone", options: [["warehouse_received", "Warehouse received"], ["inspection_passed", "Inspection passed"], ["carrier_delivered", "Carrier delivered"]] },
            ...(choice === "carrier_delivered" ? trackingFields : [])];
        case "replacement": return [{ key: "replacement_reference", label: "Replacement order or shipment reference" },
            { key: "milestone", label: "Required milestone", options: [["shipped", "Shipped"], ["delivered", "Delivered"]] }, ...trackingFields];
        case "order_cancellation": return [{ key: "shopify_order_id", label: "Shopify order ID", optional: true, hint: "gid://shopify/Order/…" },
            { key: "paypal_authorization_id", label: "PayPal authorization ID", optional: true }];
        case "subscription": return [{ key: "action", label: "Agreed action", options: [["cancel", "Cancel subscription"], ["pause", "Pause subscription"]] },
            { key: "paypal_subscription_id", label: "PayPal subscription ID" }];
        case "store_credit_or_exchange": return [{ key: "action", label: "Agreed action", options: [["store_credit", "Issue store credit"], ["exchange", "Ship exchange"]] },
            ...(choice === "exchange" ? [{ key: "fulfillment_id", label: "Shopify fulfillment ID" }, { key: "shopify_order_id", label: "Shopify order ID" },
                { key: "exchange_line_item_id", label: "Shopify exchange line item ID" }]
                : [{ key: "credit_transaction_id", label: "Shopify credit transaction ID" }, { key: "credit_account_id", label: "Shopify credit account ID" },
                    { key: "amount", label: "Credit amount", money: true }, { key: "currency", label: "Currency code", hint: "USD" }])];
        case "billing_correction": return [{ key: "action", label: "Correction", options: [["cancel_invoice", "Cancel invoice"], ["duplicate_charge", "Correct duplicate charge"], ["incorrect_amount", "Correct incorrect charge amount"]] },
            ...(choice === "duplicate_charge" ? [{ key: "original_capture_id", label: "Other PayPal capture ID" }] : choice === "incorrect_amount" ? [] :
                [{ key: "paypal_invoice_id", label: "PayPal invoice ID" }])];
        case "dispute_handoff": return [{ key: "paypal_dispute_id", label: "PayPal dispute ID" }];
    }
}
function localDateValue(iso?: string | null) {
    if (!iso)
        return "";
    const d = new Date(iso);
    return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}
/** Initial values for a new promise, e.g. from an AI suggestion. Ignored when editing. */
export type PromiseDraft = {
    kind: Remedy;
    action?: string;
    amount?: string;
    promise: string;
    source_note: string;
    source_reference: string;
};
export function PromiseForm({ item, edit, draft: suggested, linkedPayment, onClose, onSave }: {
    item: CaseView;
    edit?: PromiseView;
    draft?: PromiseDraft;
    linkedPayment?: LegacyCase | null;
    onClose: () => void;
    onSave: (terms: Terms, edit?: PromiseView) => Promise<void>;
}) {
    const draft = edit ? undefined : suggested;
    const { busy, error, submit } = useSubmission();
    const [kind, setKind] = useState<Remedy>(edit?.terms.target.kind ?? draft?.kind ?? (item.refund_case_id && !item.promises.some((p) => p.terms.target.kind === "refund") ? "refund" : "return"));
    const [choice, setChoice] = useState(String(edit?.terms.target.action ?? edit?.terms.target.milestone ?? draft?.action ?? ""));
    const eligible = edit ? item.promises.slice(0, item.promises.findIndex((p) => p.id === edit.id)) : item.promises;
    const fields = specs(kind, choice);
    return <Modal title={edit ? "Revise promise" : "Record a promise"} description={edit ? "The previous version stays in the timeline. Review the evidence again after changing the terms."
            : draft ? "Pre-filled from an AI suggestion. Check every field against the conversation before recording." : "Record what was agreed and how the result should be checked."} onClose={onClose} busy={busy}>
    <form onSubmit={(event) => submit(event, async (data) => {
            const target: Target = { kind };
            const tracking: Record<string, string> = {};
            for (const spec of fields) {
                const entry = value(data, spec.key);
                if (trackingFields.some((f) => f.key === spec.key))
                    tracking[spec.key] = entry;
                else if (entry)
                    target[spec.key] = spec.key === "currency" ? entry.toUpperCase() : entry;
            }
            if (kind === "refund")
                target.currency = "USD";
            if (Object.keys(tracking).length)
                target.tracking = tracking;
            else if (kind === "return" && edit?.terms.target.milestone === target.milestone && edit?.terms.target.tracking)
                target.tracking = edit.terms.target.tracking;
            const due = value(data, "due_at");
            const requires = data.getAll("requires").map(String);
            if (requires.length > 8)
                throw new Error("Choose at most eight prerequisite promises.");
            await onSave({
                promise: value(data, "promise"), source_note: value(data, "source_note"), source_reference: value(data, "reference") || null,
                due_at: due ? new Date(due).toISOString() : null, target, requires,
            }, edit);
        })}>
      <div className="modal-body">
        {error && <Notice>{error}</Notice>}
        {field("Remedy", <select value={kind} onChange={(event) => { setKind(event.target.value as Remedy); setChoice(""); }} disabled={!!edit}>
          {Object.entries(remedyLabels).map(([key, label]) => <option key={key} value={key} disabled={(key === "refund" || key === "dispute_handoff") && !item.refund_case_id}>{label}</option>)}
        </select>)}
        {field("Promise to the customer", <textarea name="promise" required rows={2} maxLength={3000} autoFocus defaultValue={edit?.terms.promise ?? draft?.promise}/>)}
        <div className="field-grid" key={kind}>
          {fields.map((spec) => {
            const target = edit?.terms.target;
            const existing = target?.[spec.key] ?? (target?.tracking as Record<string, string> | undefined)?.[spec.key];
            const suggestedAmount = kind === draft?.kind && spec.key === "amount" && kind === "refund" ? draft.amount : undefined;
            const initial = String(existing ?? suggestedAmount ?? (kind === "refund" && spec.key === "amount" ? linkedPayment?.commitment?.amount ?? "" : ""));
            return <div key={spec.key}>{field(spec.label, spec.options
                    ? <select name={spec.key} value={choice || spec.options[0][0]} onChange={(event) => setChoice(event.target.value)}>{spec.options.map(([val, name]) => <option value={val} key={val}>{name}</option>)}</select>
                    : <input name={spec.key} defaultValue={initial} placeholder={spec.hint} required={!spec.optional} pattern={spec.money ? "[0-9]+(\\.[0-9]{1,2})?" : undefined} inputMode={spec.money ? "decimal" : undefined} maxLength={160}/>)}</div>;
        })}
        </div>
        {field("Source evidence", <textarea name="source_note" required rows={2} maxLength={3000} defaultValue={edit?.terms.source_note ?? draft?.source_note} placeholder="Quote or describe the recorded agreement."/>)}
        <div className="field-grid">
          {field("Source reference (optional)", <input name="reference" maxLength={160} defaultValue={edit?.terms.source_reference ?? draft?.source_reference ?? ""} placeholder="Support ticket or receipt ID"/>)}
          {field("Due date (optional)", <input type="datetime-local" name="due_at" defaultValue={localDateValue(edit?.terms.due_at)}/>)}
        </div>
        {eligible.length > 0 && <fieldset className="prerequisites"><legend>Prerequisites (optional)</legend>
          {eligible.map((p) => <label key={p.id}><input type="checkbox" name="requires" value={p.id} defaultChecked={edit?.terms.requires.includes(p.id)}/>{p.terms.promise}</label>)}
        </fieldset>}
      </div>
      {footer(onClose, busy, edit ? "Save revision" : "Record promise")}
    </form>
  </Modal>;
}
export function EvidenceForm({ promise, onClose, onSave }: {
    promise: PromiseView;
    onClose: () => void;
    onSave: (data: unknown) => Promise<void>;
}) {
    const { busy, error, submit } = useSubmission();
    const internal = promise.terms.target.kind === "return" && promise.terms.target.milestone !== "carrier_delivered";
    return <Modal title="Record evidence" description="This will be attributed to the merchant in the timeline." onClose={onClose} busy={busy}>
    <form onSubmit={(event) => submit(event, (data) => onSave({
            expected_revision: promise.revision, note: value(data, "note"), reference: value(data, "reference") || null,
            finding: internal ? value(data, "finding") : "note",
        }))}>
      <div className="modal-body">{error && <Notice>{error}</Notice>}
        {internal && field("Internal milestone", <select name="finding" defaultValue="note">
          <option value="note">Add a note</option><option value="confirmed">Confirm milestone</option><option value="not_confirmed">Could not confirm</option>
        </select>)}
        {field("Evidence note", <textarea name="note" rows={3} required maxLength={3000} autoFocus/>)}
        {field("Reference (optional)", <input name="reference" maxLength={160} placeholder="Warehouse or support reference"/>)}
      </div>
      {footer(onClose, busy, "Save evidence")}
    </form>
  </Modal>;
}
export function RefundForm({ amount, initial, approval, onClose, onApprove, onExecute }: {
    amount: string;
    initial?: string;
    approval?: Approval;
    onClose: () => void;
    onApprove: (note: string, requested: string) => Promise<void>;
    onExecute: (approval: Approval) => Promise<void>;
}) {
    const { busy, error, submit } = useSubmission();
    const [requested, setRequested] = useState(initial ?? amount);
    const cents = amountCents(requested);
    const valid = cents !== null && cents > 0 && cents <= (amountCents(amount) ?? 0);
    return <Modal title={approval ? "Submit approved refund" : "Review exact refund"} description={approval ? "Resolve will check PayPal again before submitting." : "Approve the exact amount for this payment. Submission is a separate step."} onClose={onClose} busy={busy}>
    <form onSubmit={(event) => submit(event, (data) => {
            if (approval)
                return onExecute(approval);
            if (!valid)
                throw new Error(`Enter an amount between $0.01 and ${money(amount)}.`);
            return onApprove(value(data, "note"), centsText(cents!));
        })}>
      <div className="modal-body">
        {error && <Notice>{error}</Notice>}
        <div className="confirm-amount"><span>{approval ? "Approved amount" : "Available to approve"}</span><strong>{money(amount)}</strong></div>
        <Notice tone="info">{"PayPal Sandbox only. The backend checks the balance and approval before submitting."}</Notice>
        {!approval && field("Refund amount (USD)", <input name="refund_amount" value={requested} onChange={(event) => setRequested(event.target.value)} required inputMode="decimal" aria-invalid={requested.length > 0 && !valid}/>, `Up to ${money(amount)}. You can approve a smaller partial refund.`)}
        {!approval && field("Decision note", <textarea name="note" required rows={2} maxLength={5000} autoFocus placeholder="Why is this refund approved?"/>)}
      </div>
      {footer(onClose, busy, approval ? ("Submit Sandbox refund") : valid ? `Approve ${money(centsText(cents!))}` : "Approve refund")}
    </form>
  </Modal>;
}
export function ReviewForm({ onClose, onSave }: {
    onClose: () => void;
    onSave: (note: string) => Promise<void>;
}) {
    const { busy, error, submit } = useSubmission();
    return <Modal title="Resolve review item" description="Record why this item no longer needs review." onClose={onClose} busy={busy}>
    <form onSubmit={(event) => submit(event, (data) => onSave(value(data, "note")))}>
      <div className="modal-body">{error && <Notice>{error}</Notice>}
        {field("Resolution note", <textarea name="note" required rows={3} maxLength={1000} autoFocus/>)}
      </div>{footer(onClose, busy, "Resolve item")}
    </form>
  </Modal>;
}
export function LocalGuide({ onClose }: {
    onClose: () => void;
}) {
    return <Modal title="Using Resolve locally" description="Use your merchant account to manage recorded cases and configured provider evidence." onClose={onClose}>
    <div className="modal-body">
      <p><Link href="/docs">Read the complete Resolve documentation →</Link></p>
      <div className="guide-item"><span className="guide-icon"><KeyRound size={17}/></span><div><strong>Connect a merchant</strong><p>Sign in at /account with your staff account or use a private merchant key at /login.</p></div></div>
      <div className="guide-item"><span className="guide-icon"><LockKeyhole size={17}/></span><div><strong>Review before moving money</strong><p>Evidence checks and approvals do not issue a refund. Submit is a separate action, and connected payments use PayPal Sandbox.</p></div></div>
    </div><div className="modal-footer"><Button onClick={onClose}>Got it</Button></div>
  </Modal>;
}
