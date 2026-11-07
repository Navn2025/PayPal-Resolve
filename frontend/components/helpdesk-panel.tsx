"use client";

import { useEffect, useState, type FormEvent } from "react";
import { ArrowUpRight, Headphones, RefreshCw } from "lucide-react";
import { pretty, timeText, type Requester } from "@/lib/domain";
import { Button, Notice } from "./ui";

type Helpdesk = { configured: boolean; ticket: { ticket_id: number; status: string; checked_at: string; url: string } | null };

export function HelpdeskPanel({ caseId, request }: { caseId: string; request: Requester }) {
  const root = "/resolution-cases/" + caseId + "/helpdesk";
  const [state, setState] = useState<Helpdesk | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const explain = (failure: unknown) => failure instanceof Error ? failure.message : "Could not verify the ticket.";
  useEffect(() => {
    let active = true;
    request<Helpdesk>(root).then((result) => { if (active) setState(result); })
      .catch((failure) => { if (active) setError(explain(failure)); });
    return () => { active = false; };
  }, [request, root]);
  async function save(id: number) {
    setBusy(true); setError("");
    try { setState(await request<Helpdesk>(root, "PUT", { ticket_id: id })); }
    catch (failure) { setError(explain(failure)); }
    finally { setBusy(false); }
  }
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const id = Number(new FormData(event.currentTarget).get("ticket"));
    if (Number.isSafeInteger(id) && id > 0) void save(id);
  }
  if (!state?.configured && !error) return null;
  const ticket = state?.ticket;
  return <section className="section-card helpdesk-panel customer-print-hide">
    <div className="section-head"><div><div className="eyebrow">HELPDESK</div><h3>Zendesk ticket</h3></div><Headphones size={17} /></div>
    {error && <Notice>{error}</Notice>}
    {ticket && <div className="account-actions">
      <p><strong>#{ticket.ticket_id} · {pretty(ticket.status)}</strong> <small>· Checked {timeText(ticket.checked_at)}</small></p>
      <div className="customer-share-actions"><a href={ticket.url} target="_blank" rel="noreferrer" className="button button-secondary small-button">Open in Zendesk <ArrowUpRight size={14} /></a>
        <Button className="small-button" disabled={busy} onClick={() => void save(ticket.ticket_id)}><RefreshCw size={14} /> Refresh ticket</Button></div>
    </div>}
    {state?.configured && <form onSubmit={submit} className="helpdesk-form">
      <label className="field"><span>{ticket ? "Replace ticket ID" : "Zendesk ticket ID"}</span><input name="ticket" inputMode="numeric" pattern="[1-9][0-9]{0,15}" required /></label>
      <Button disabled={busy} type="submit">{ticket ? "Replace ticket" : "Link ticket"}</Button>
    </form>}
  </section>;
}
