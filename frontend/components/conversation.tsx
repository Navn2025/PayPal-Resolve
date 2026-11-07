"use client";

import { useRef, useState, type FormEvent } from "react";
import { MessageCircle, RefreshCw, Send } from "lucide-react";
import { timeText, uuid } from "@/lib/domain";
import type { Message } from "@/lib/customer";
import { Button, Notice } from "./ui";

export function Conversation({ messages, viewer, onSend, onRefresh, refreshing, inactive = false }: {
  messages: Message[]; viewer: Message["sender"]; onSend: (body: string, requestId: string) => Promise<void>;
  onRefresh?: () => void; refreshing: boolean; inactive?: boolean;
}) {
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const retry = useRef<{ body: string; id: string } | null>(null);
  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (sending || inactive || !draft.trim()) return;
    const body = draft.trim();
    if (retry.current?.body !== body) retry.current = { body, id: uuid() };
    setSending(true); setError("");
    try {
      await onSend(body, retry.current.id);
      retry.current = null; setDraft("");
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Could not save the message."); }
    finally { setSending(false); }
  }
  return <section className="section-card customer-conversation customer-print-hide">
    <div className="section-head"><div><div className="eyebrow">FOLLOW-UP</div><h3>{viewer === "merchant" ? "Customer conversation" : "Messages"}</h3></div>
      {onRefresh && <Button className="small-button" onClick={onRefresh} disabled={refreshing}><RefreshCw size={15} className={refreshing ? "spin" : ""} /> Refresh messages</Button>}</div>
    {error && <Notice>{error}</Notice>}
    {messages.length === 0 ? <div className="conversation-empty"><MessageCircle size={20} /><p>No messages yet.</p></div> :
      <ol className="conversation-list" aria-label="Case messages" aria-live="polite">
        {messages.map((message) => <li key={message.id} className={message.sender === viewer ? "conversation-own" : ""}>
          <div><strong>{message.sender === viewer ? "You" : message.sender === "merchant" ? "Merchant" : "Customer"}</strong>
            <time dateTime={message.created_at}>{timeText(message.created_at)}</time></div>
          <p>{message.body}</p>
        </li>)}
      </ol>}
    <form onSubmit={send} className="conversation-compose">
      <label className="field"><span>{viewer === "merchant" ? "Reply to customer" : "Write a message"}</span>
        <textarea rows={3} maxLength={2000} value={draft} disabled={sending || inactive} onChange={(event) => setDraft(event.target.value)}
          placeholder={inactive ? "Create a customer link to enable replies." : viewer === "merchant" ? "Write an update the customer can see…" : "Ask a question or share an update…"} /></label>
      <div><small>{draft.length}/2000</small><Button type="submit" variant="primary" disabled={sending || inactive || !draft.trim()}>
        <Send size={15} /> {sending ? "Sending…" : "Send message"}</Button></div>
    </form>
  </section>;
}
