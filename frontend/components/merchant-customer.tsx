"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowUpRight, CheckCheck, Copy, KeyRound, Link2, LockKeyhole } from "lucide-react";
import { timeText, type CaseView, type Requester } from "@/lib/domain";
import { downloadFile, type CustomerLink, type Evidence, type IssuedCustomerLink, type Message, type Operations } from "@/lib/customer";
import { EvidencePanel } from "./customer-actions";
import { Conversation } from "./conversation";
import { Button, Notice } from "./ui";

export function MerchantCustomer({ item, request, demo, onOperations }: {
  item: CaseView; request: Requester; demo: boolean; onOperations: (id: string, operations: Operations) => void;
}) {
  const root = "/resolution-cases/" + item.id;
  const [link, setLink] = useState<CustomerLink | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [visibleWatermark, setVisibleWatermark] = useState(0);
  const [title, setTitle] = useState("Your resolution");
  const [shareOrder, setShareOrder] = useState(false);
  const [issuedUrl, setIssuedUrl] = useState("");
  const [loading, setLoading] = useState(!demo);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const loadingSettings = loading && !link;
  const linkInput = useRef<HTMLInputElement>(null);
  const latest = useRef(0);
  const explain = (failure: unknown) => failure instanceof Error ? failure.message : "Could not update the customer portal.";
  const refresh = useCallback(async (initial = false) => {
    if (demo) return;
    const version = ++latest.current;
    setLoading(true); setError("");
    try {
      const [status, files, operations, thread] = await Promise.all([
        request<CustomerLink>(root + "/customer-link"), request<Evidence[]>(root + "/customer-evidence"),
        request<Operations>(root + "/operations"), request<Message[]>(root + "/customer-messages"),
      ]);
      if (version !== latest.current) return;
      setLink(status); setMessages(thread); setEvidence(files); setVisibleWatermark(operations.message_watermark);
      onOperations(item.id, operations);
      if (initial) { setTitle(status.title ?? "Your resolution"); setShareOrder(status.show_order_reference); }
      if (!status.active) setIssuedUrl("");
    } catch (failure) { if (version === latest.current) setError(explain(failure)); }
    finally { if (version === latest.current) setLoading(false); }
  }, [demo, item.id, onOperations, request, root]);

  useEffect(() => {
    void refresh(true);
    return () => { latest.current += 1; };
  }, [refresh]);

  if (demo) return <section className="section-card customer-share">
    <div className="section-head"><div><div className="eyebrow">CUSTOMER ACCESS</div><h3>Customer portal</h3></div><span className="section-icon"><Link2 size={20} /></span></div>
    <p>A customer sees the agreed remedy, progress, and messages for their case. Open the sample to see their experience.</p>
    <a className="button button-primary" href="/customer?demo=1" target="_blank" rel="noreferrer">Open customer demo <ArrowUpRight size={15} /></a>
    <p className="muted">Connect your merchant account to create a private link for a real case.</p>
  </section>;

  async function issue(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setNotice(""); setError("");
    try {
      const { token, public_url, ...status } = await request<IssuedCustomerLink>(root + "/customer-link", "POST", {
        title: title.trim(), show_order_reference: shareOrder,
      });
      setLink(status);
      setIssuedUrl(public_url ?? window.location.origin + "/customer#" + token);
      setNotice("Private customer link created.");
    } catch (failure) { setError(explain(failure)); }
    finally { setBusy(false); }
  }
  async function revoke() {
    if (busy) return;
    setBusy(true); setError(""); setNotice("");
    try {
      setLink(await request<CustomerLink>(root + "/customer-link", "DELETE"));
      setIssuedUrl(""); setNotice("Customer access revoked.");
    } catch (failure) { setError(explain(failure)); }
    finally { setBusy(false); }
  }
  async function copy() {
    try { await navigator.clipboard.writeText(issuedUrl); setNotice("Link copied."); }
    catch { linkInput.current?.focus(); linkInput.current?.select(); setNotice("Copy the selected link to share it."); }
  }
  async function markRead() {
    setBusy(true); setError("");
    try {
      const operations = await request<Operations>(root + "/operations/read", "POST", { through: visibleWatermark });
      onOperations(item.id, operations);
      if (operations.message_watermark > visibleWatermark) await refresh();
    } catch (failure) { setError(explain(failure)); }
    finally { setBusy(false); }
  }
  return <>
    <section className="section-card customer-share">
      <div className="section-head"><div><div className="eyebrow">CUSTOMER ACCESS</div><h3>Share with customer</h3></div>
        <span className="provider-chip"><LockKeyhole size={13} /> {link?.active ? "Link active" : "No active link"}</span></div>
      <p>Anyone with the link can see the shared timeline, promises, conversation, and customer uploads. Internal notes and payment records stay private.</p>
      {error && <Notice>{error}</Notice>}{notice && <Notice tone="success">{notice}</Notice>}
      {loading && !link && <p className="muted">Checking link status…</p>}
      {link?.active && link.expires_at && <p className="muted">Expires {timeText(link.expires_at)}. Replacing the link invalidates the old one.</p>}
      {issuedUrl && <div className="customer-link-box">
        <label className="field"><span>Private customer link</span><input ref={linkInput} value={issuedUrl} readOnly /></label>
        <div><Button onClick={copy}><Copy size={15} /> Copy link</Button>
          <a href={issuedUrl} className="button button-secondary" target="_blank" rel="noreferrer">Open customer view <ArrowUpRight size={15} /></a></div>
      </div>}
      {link?.active && !issuedUrl && <p className="muted">The private URL was shown when it was created. Replace it if you need a new copy.</p>}
      <form className="customer-share-form" onSubmit={issue}>
        <label className="field"><span>Customer heading</span><input value={title} onChange={(event) => setTitle(event.target.value)} disabled={loadingSettings || busy} required maxLength={120} /></label>
        {item.order_reference && <label className="customer-checkbox"><input type="checkbox" checked={shareOrder} onChange={(event) => setShareOrder(event.target.checked)} disabled={loadingSettings || busy} /> Show order reference ({item.order_reference})</label>}
        <div className="customer-share-actions"><Button type="submit" variant="primary" disabled={loading || busy}>
          <KeyRound size={15} /> {busy ? "Saving…" : link?.active ? "Replace customer link" : "Create customer link"}</Button>
          {link?.active && <Button onClick={revoke} disabled={busy || loading}>Revoke access</Button>}</div>
      </form>
    </section>
    {!!item.operations?.unread_count && <div className="conversation-read">
      <span className="unread-chip">{item.operations.unread_count} unread</span>
      <Button className="small-button" disabled={busy || loading || !visibleWatermark} onClick={markRead}><CheckCheck size={16} /> Mark messages read</Button>
    </div>}
    <Conversation messages={messages} viewer="merchant" refreshing={loading || busy} onRefresh={() => void refresh()} inactive={!link?.active || busy}
      onSend={async (body, requestId) => {
        latest.current += 1; setLoading(false);
        const message = await request<Message>(root + "/customer-messages", "POST", { body, request_id: requestId });
        setMessages((items) => items.some((entry) => entry.id === message.id) ? items : [...items, message]);
      }} />
    <EvidencePanel files={evidence} onDownload={(file) => downloadFile("/api/resolve" + root + "/customer-evidence/" + file.id, file.filename)} />
  </>;
}
