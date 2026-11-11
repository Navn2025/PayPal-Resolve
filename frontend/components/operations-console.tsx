"use client";

import Link from "next/link";
import { ReturnPolicyEditor } from "./assurance";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { platform, failureText } from "@/lib/platform";
import { backendRequest } from "@/lib/http";
import { Activity, CircleAlert, Clock3, Layers3, RefreshCw, Timer } from "lucide-react";
import { Button, Notice } from "./ui";
import { WorkspaceShell } from "./workspace-shell";

type Tab = "overview" | "alerts" | "imports" | "team" | "connections" | "audit";
interface Me { merchant: { id: string; name: string }; actor_id: string; role: string }
interface Staff { id: string; name: string; email: string; role: string; active: number }
interface Connection { provider: string; revision: number; enabled: boolean; config: Record<string, string | boolean>; check_status: string; checked_at: string | null }
interface Ticket { id: string; title: string; ticket_id: string; state: string; case_id: string | null; order_reference: string | null; suggestions?: { status: string; proposals: unknown[] } | null; messages?: { source_id: string; sender: string; body: string; public: number; sent_at: string }[] }
interface Alert { id: string; case_id: string; reason: string; assignee: string | null; customer_draft: string; day: string }
interface Dashboard { case_count: number; outcomes: Record<string, number>; remedies: Record<string, number>; complaint_reasons: Record<string, number>; overdue_promises: number; awaiting_evidence: number; financial: { promised: string; completed: string; pending: string; outstanding_excluding_pending: string; shared_capture_count: number }; resolution_time: { sample_count: number; average_hours: number | null } }
const roles = ["manager", "finance", "agent", "viewer"];
const providerFields: Record<string, { config: [string, string][]; secrets: [string, string][] }> = {
  paypal: { config: [["merchant_id", "Sandbox seller merchant ID"]], secrets: [["client_id", "Sandbox client ID"], ["client_secret", "Sandbox client secret"]] },
  zendesk: { config: [["subdomain", "Zendesk subdomain"]], secrets: [["oauth_token", "OAuth access token"], ["webhook_secret", "Webhook signing secret"]] },
  shopify: { config: [["shop_domain", "Shop hostname (store.myshopify.com)"]], secrets: [["admin_token", "Admin API access token"]] },
  easypost: { config: [], secrets: [["api_key", "API key"]] },
};

export function OperationsNavigation() {
  return <nav className="ops-navigation" aria-label="Workspace navigation"><Link href="/workspace">Cases</Link><Link href="/workspace/orders">Orders</Link><Link href="/workspace/operations">Operations</Link><Link href="/workspace/settings">Settings</Link></nav>;
}

function ConnectionEditor({ provider, current, owner, saved }: { provider: string; current?: Connection; owner: boolean; saved: () => Promise<void> }) {
  const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget; const values = new FormData(form); setBusy(true); setError("");
    const fields = providerFields[provider];
    const config: Record<string, string | boolean> = Object.fromEntries(fields.config.map(([key]) => [key, String(values.get(key) ?? "")]));
    if (provider === "paypal") { config.refunds_enabled = values.has("refunds_enabled"); config.partial_refunds_enabled = values.has("partial_refunds_enabled"); }
    const credentials = Object.fromEntries(fields.secrets.map(([key]) => [key, String(values.get(key) ?? "")]).filter(([, value]) => value));
    try { await platform("connections/" + provider, "PUT", { expected_revision: current?.revision ?? 0, enabled: values.has("enabled"), config, credentials }); form.reset(); await saved(); }
    catch (failure) { setError(failureText(failure)); } finally { setBusy(false); }
  }
  return <article className="section-card"><h3>{provider === "paypal" ? "PayPal Sandbox" : provider === "easypost" ? "EasyPost" : provider[0].toUpperCase() + provider.slice(1)}</h3>
    <p>{current ? `${current.enabled ? "Enabled" : "Disabled"} · ${current.check_status.replaceAll("_", " ")}` : "Account not connected"}</p>
    {error && <Notice>{error}</Notice>}
    {owner && <form key={current?.revision ?? 0} className="ops-form" onSubmit={submit}>
      {providerFields[provider].config.map(([key, label]) => <label key={key}>{label}<input name={key} required maxLength={160} defaultValue={String(current?.config[key] ?? "")} autoComplete="off" /></label>)}
      {providerFields[provider].secrets.map(([key, label]) => <label key={key}>{label}<input name={key} type="password" autoComplete="new-password" maxLength={4096} placeholder={current ? "Leave blank to keep the saved value" : "Enter privately"} /></label>)}
      <label className="ops-check"><input type="checkbox" name="enabled" defaultChecked={current?.enabled ?? false} /> Enable connection</label>
      {provider === "paypal" && <><label className="ops-check"><input type="checkbox" name="refunds_enabled" defaultChecked={!!current?.config.refunds_enabled} /> Allow separately approved Sandbox refunds</label><label className="ops-check"><input type="checkbox" name="partial_refunds_enabled" defaultChecked={!!current?.config.partial_refunds_enabled} /> Allow history-verified partial refunds</label></>}
      <div className="ops-actions"><Button type="submit" disabled={busy}>{busy ? "Saving…" : "Save connection"}</Button>
        {current?.enabled && <Button type="button" disabled={busy} onClick={async () => { setBusy(true); setError(""); try { await platform("connections/" + provider + "/check", "POST"); await saved(); } catch (f) { setError(failureText(f)); } finally { setBusy(false); } }}>Check account access</Button>}</div>
    </form>}
    {provider === "paypal" && <small>A credential check does not prove seller ownership. Payment evidence must match this seller before any refund.</small>}
  </article>;
}

export function OperationsConsole() {
  const [ready, setReady] = useState(false);
  const [tab, setTab] = useState<Tab>("overview"); const [me, setMe] = useState<Me | null>(null); const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null); const [alerts, setAlerts] = useState<Alert[]>([]); const [staff, setStaff] = useState<Staff[]>([]);
  const [connections, setConnections] = useState<Connection[]>([]); const [imports, setImports] = useState<Ticket[]>([]); const [selected, setSelected] = useState<Ticket | null>(null);
  const [cases, setCases] = useState<{ id: string; title: string; order_reference: string | null }[]>([]);
  const [invitation, setInvitation] = useState(""); const [key, setKey] = useState(""); const [keys, setKeys] = useState<{ id: string; created_at: string; support_source?: string | null }[]>([]);
  const [keySource, setKeySource] = useState("my-store");
  const [audit, setAudit] = useState<{ id: string; actor_id: string; action: string; recorded_at: string }[]>([]);
  const loadSequence = useRef(0);
  const [loading,setLoading] = useState(true);
  async function load() {
    const sequence=++loadSequence.current;
    setError(""); setLoading(true);
    const current=()=>sequence===loadSequence.current;
    try {
      if (tab === "overview") { const data=await platform<Dashboard>("dashboard"); if(current())setDashboard(data); }
      if (tab === "alerts") { const data=await platform<{items:Alert[]}>("watchdog"); if(current())setAlerts(data.items); }
      if (tab === "team") { const data=await platform<{items:Staff[]}>("team"); if(current())setStaff(data.items); }
      if (tab === "connections") {
        const [data,keyData]=await Promise.all([platform<{items:Connection[]}>("connections"),platform<{items:typeof keys}>("sdk-keys")]);
        if(current()){setConnections(data.items);setKeys(keyData.items);}
      }
      if (tab === "imports") {
        const [data,caseData]=await Promise.all([platform<{items:Ticket[]}>("imports"),backendRequest<{items:typeof cases}>("/resolution-cases?limit=100")]);
        if(current()){setImports(data.items);setCases(caseData.items);}
      }
      if (tab === "audit") {const data=await platform<{items:typeof audit}>("audit");if(current())setAudit(data.items);}
    } catch(failure){if(current())setError(failureText(failure));}
    finally{if(current())setLoading(false);}
  }
  useEffect(()=>{
    let active=true;
    void platform<Me>("me").then(identity=>{if(active)setMe(identity);}).catch(failure=>{if(active)setError(failureText(failure));});
    return()=>{active=false;loadSequence.current++;};
  },[]);
  useEffect(() => { setReady(true); void load(); }, [tab]);
  async function act(action: () => Promise<void>) { setBusy(true); setError(""); try { await action(); } catch (f) { setError(failureText(f)); } finally { setBusy(false); } }
  const owner = me?.role === "owner";
  const write = !!me && me.role !== "viewer";
  // The shared workspace frame and the workspace header, metric cards and case tabs; sections keep the existing card style.
  const metrics = dashboard ? [
    { label: "Cases", value: String(dashboard.case_count), Icon: Layers3, tone: "blue" },
    { label: "Overdue promises", value: String(dashboard.overdue_promises), Icon: CircleAlert, tone: "amber" },
    { label: "Awaiting evidence", value: String(dashboard.awaiting_evidence), Icon: Clock3, tone: "purple" },
    { label: "Average resolution", value: dashboard.resolution_time.average_hours === null ? "—" : `${dashboard.resolution_time.average_hours} hours`,
      note: dashboard.resolution_time.average_hours === null ? "No closed-case sample" : undefined, Icon: Timer, tone: "green" },
  ] : [];
  return <WorkspaceShell active="operations" merchant={me ? { name: me.merchant.name } : null} contentId="operations-content"><div className="ops-page">
    <div className="workspace-intro"><div><div className="eyebrow intro-eyebrow"><span /> Merchant operations</div><h1>Keep every commitment moving.</h1>
      <p>Review the work, resolve the gaps, and give buyers a clear next step.</p>
      {me && <p className="intro-identity"><Activity size={13} /> {me.merchant.name} · {me.role}</p>}</div>
      <div className="intro-actions"><Button disabled={busy||loading} onClick={() => void act(load)}><RefreshCw size={15} /> Refresh</Button></div></div>
    <nav className="case-tabs ops-tabs-bar" aria-label="Operations sections">{(["overview", "alerts", "imports", "team", "connections", "audit"] as Tab[]).map(t => <button type="button" key={t} className={tab === t ? "active" : ""} disabled={!ready || !me} onClick={() => { setTab(t); setSelected(null); }} aria-current={tab === t ? "page" : undefined}>{t === "alerts" ? "Missed promises" : t === "imports" ? "Support imports" : t[0].toUpperCase() + t.slice(1)}</button>)}</nav>
    {error && <Notice>{error}</Notice>}
    {loading && <p className="panel-state" role="status">Loading {tab === "alerts" ? "missed promises" : tab}…</p>}
    {tab === "overview" && dashboard && <>
      <div className="metrics-wrap" aria-label="Operations metrics"><div className="metrics-grid">{metrics.map(({ label, value, note, Icon, tone }) => <div className="status-metric" key={label}>
        <span className={`metric-icon metric-${tone}`}><Icon size={18} /></span>
        <div><span>{label}</span><strong>{value}</strong>{note && <small className="metric-note">{note}</small>}</div></div>)}</div></div>
      <section className="section-card"><h2>Recorded refund balances</h2><p>USD totals count each shared capture once. Recorded refunds still require independent provider checks before financial action.</p>
        <div className="ops-metrics">{[["Promised", dashboard.financial.promised], ["Completed", dashboard.financial.completed], ["Pending", dashboard.financial.pending], ["Outstanding, excluding pending", dashboard.financial.outstanding_excluding_pending]].map(([label, amount]) => <div key={label}><span>{label}</span><strong>${amount}</strong></div>)}</div>
        <small>{dashboard.financial.shared_capture_count} shared capture balances · Resolution time uses {dashboard.resolution_time.sample_count} known closed-case timestamps.</small>
      </section><div className="ops-columns">{[["Case outcomes", dashboard.outcomes], ["Remedies", dashboard.remedies], ["Complaint reasons", dashboard.complaint_reasons]].map(([title, values]) => <section className="section-card" key={String(title)}><h2>{String(title)}</h2>{Object.entries(values).map(([label, count]) => <p className="ops-row" key={label}><span>{label.replaceAll("_", " ")}</span><strong>{count}</strong></p>)}{!Object.keys(values).length && <p>No records yet.</p>}</section>)}</div>
    </>}
    {tab === "alerts" && <section className="section-card"><div className="ops-row"><div><h2>Missed promises</h2><p>Daily alerts use the current promise revision and evidence. Updates remain drafts until a merchant sends them.</p></div>{write && <Button disabled={busy} onClick={() => void act(async () => { setAlerts((await platform<{ items: Alert[] }>("watchdog/scan", "POST")).items); })}>Scan workspace</Button>}</div>
      {!alerts.length && <p>No open alerts. Run a scan or wait for the operations worker.</p>}{alerts.map(a => <article className="ops-record" key={a.id}><div className="ops-row"><strong>{a.reason}</strong><span>{a.day} · {a.assignee ?? "Workspace owner"}</span></div><p>{a.customer_draft}</p><div className="ops-actions"><Link href={"/workspace?case=" + a.case_id}>Open case</Link><Button onClick={() => void navigator.clipboard.writeText(a.customer_draft)}>Copy update draft</Button></div></article>)}
    </section>}
    {tab === "imports" && <section className="section-card"><h2>Support conversation imports</h2><p>Signed Zendesk events import automatically while the operations worker runs. An exact order match can link a case; uncertain matches stay here for review. Private notes remain private.</p>
      {write && <form className="ops-inline-form" onSubmit={e => { e.preventDefault(); const ticketId = Number(new FormData(e.currentTarget).get("ticket")); void act(async () => { const item = await platform<Ticket>("imports/zendesk", "POST", { ticket_id: ticketId }); setSelected(item); await load(); }); }}><label>Zendesk ticket number<input name="ticket" type="number" min={1} required /></label><Button type="submit" disabled={busy}>Import ticket</Button></form>}
      <div className="ops-columns"><div>{imports.map(t => <button className="ops-import" key={t.id} onClick={() => void act(async () => setSelected(await platform<Ticket>("imports/" + t.id)))}><strong>{t.title}</strong><span>Ticket {t.ticket_id} · {t.state.replaceAll("_", " ")}</span></button>)}</div>
        {selected && <article className="ops-record"><h3>{selected.title}</h3>{selected.case_id ? <Link href={"/workspace?case=" + selected.case_id}>Open matched case and review promise suggestions</Link> : write && <form className="ops-form" onSubmit={e => { e.preventDefault(); const caseId = new FormData(e.currentTarget).get("case"); void act(async () => { setSelected(await platform<Ticket>(`imports/${selected.id}/match`, "PUT", { case_id: caseId })); await load(); }); }}><label>Confirm the correct case<select name="case" required defaultValue=""><option value="" disabled>Choose a merchant case</option>{cases.map(c => <option key={c.id} value={c.id}>{c.order_reference ?? c.title} · {c.title}</option>)}</select></label><Button type="submit" disabled={busy}>Confirm match</Button></form>}
          {selected.messages?.map(m => <div className="ops-message" key={m.source_id}><small>{m.sender} · {m.public ? "Public ticket comment" : "Private ticket note"} · {m.source_id}</small><p>{m.body}</p></div>)}
          {selected.suggestions && <p>Promise extraction: {selected.suggestions.status.replaceAll("_", " ")} · {selected.suggestions.proposals.length} proposals. Review proposals in the matched case.</p>}
        </article>}</div>
    </section>}
    {tab === "team" && <section className="section-card"><h2>People and permissions</h2><p>Agents handle cases. Managers can approve refunds. Finance can approve and submit refunds. Viewers can read. Owners manage access and connections.</p>
      {owner && !staff.some(s => s.role === "owner" && s.active) && <p><Link href="/account?claim=1">Create an individual owner account for this existing workspace</Link></p>}
      {owner && <form className="ops-inline-form" onSubmit={e => { e.preventDefault(); const data = new FormData(e.currentTarget); void act(async () => { const result = await platform<{ token: string }>("team/invites", "POST", { email: data.get("email"), role: data.get("role") }); setInvitation(window.location.origin + "/account#" + result.token); await load(); }); }}><label>Staff email<input name="email" type="email" required /></label><label>Role<select name="role" defaultValue="agent">{roles.map(r => <option key={r}>{r}</option>)}</select></label><Button type="submit" disabled={busy}>Create invitation</Button></form>}
      {invitation && <div className="ops-record"><p>Share this invitation privately with the invited person. It expires in two days and can be used once.</p><input aria-label="Private staff invitation" readOnly value={invitation} /><Button onClick={() => void navigator.clipboard.writeText(invitation)}>Copy invitation</Button></div>}
      {staff.map(s => <article className="ops-record" key={s.id}><strong>{s.name}</strong><p>{s.email} · {s.role} · {s.active ? "Active" : "Disabled"}</p>{owner && <form className="ops-inline-form" onSubmit={e => { e.preventDefault(); const data = new FormData(e.currentTarget); void act(async () => { await platform("team/" + s.id, "PUT", { role: data.get("role"), active: data.has("active") }); await load(); }); }}><label>Role<select name="role" defaultValue={s.role}>{["owner", ...roles].map(r => <option key={r}>{r}</option>)}</select></label><label className="ops-check"><input name="active" type="checkbox" defaultChecked={!!s.active} /> Active account</label><Button type="submit" disabled={busy}>Update access</Button></form>}</article>)}
    </section>}
    {tab === "connections" && <><ReturnPolicyEditor owner={owner}/><div className="ops-columns">{Object.keys(providerFields).map(p => <ConnectionEditor key={p} provider={p} current={connections.find(c => c.provider === p)} owner={owner} saved={load} />)}</div>
      {me && <section className="section-card"><h2>Zendesk webhook delivery</h2><p>Use this endpoint in a Zendesk ticket trigger, with the matching signing secret saved above. Send a ticket_id and a stable event_id. Run the operations worker to process deliveries.</p><code>{typeof window !== "undefined" ? window.location.origin : ""}/webhooks/zendesk/{me.merchant.id}</code><pre>{'{"ticket_id":"{{ticket.id}}","event_id":"{{ticket.id}}:{{ticket.updated_at}}"}'}</pre></section>}
      <section className="section-card"><h2>Customer support inside your store</h2><p>Add a “Need help?” button to your order page. Your app can open a tracked issue, show the current resolution and next step, and open the private buyer portal.</p>
        <p>Your server must verify that the signed-in customer owns the order before calling Resolve.</p>
        {owner && <form className="ops-inline-form" onSubmit={e => { e.preventDefault(); const source = String(new FormData(e.currentTarget).get("source")); void act(async () => { const result = await platform<{ api_key: string; source: string }>("support-keys", "POST", { source }); setKey(result.api_key); setKeySource(result.source); await load(); }); }}><label>App source<input name="source" defaultValue="my-store" required pattern="[A-Za-z0-9][A-Za-z0-9_.-]{0,63}" maxLength={64} /></label><Button type="submit" disabled={busy}>Generate support integration key</Button></form>}
        <pre>{'await resolve.openIssue({ orderId, requestId, reason: "damaged_item", message, requestedResolution: "replacement" });\nconst status = await resolve.getOrderResolution(orderId);'}</pre>
        <p>Support access is limited to orders from the selected app source. Existing order-only keys keep their permissions.</p>
      </section>
      <section className="section-card"><h2>Connect your app</h2><p>Use a scoped SDK key on your app server to sync orders. The key cannot sign in or execute refunds.</p>{owner && <Button disabled={busy} onClick={() => void act(async () => { const result = await platform<{ api_key: string }>("sdk-keys", "POST"); setKey(result.api_key); setKeySource("my-store"); await load(); })}>Generate SDK key</Button>}
        {key && <div className="ops-record"><p>This key is shown once. Save it privately on your server.</p><input type="password" aria-label="New SDK key" readOnly value={key} /><Button onClick={() => void navigator.clipboard.writeText(key)}>Copy key</Button><pre>{`RESOLVE_API_URL=${typeof window !== "undefined" ? window.location.origin : ""}/api/sdk\nRESOLVE_API_KEY=<paste-the-key>\nRESOLVE_APP_SOURCE=${keySource}`}</pre></div>}
        {keys.map(k => <p className="ops-row" key={k.id}><span>{k.id} · {new Date(k.created_at).toLocaleDateString()}</span>{owner && <Button disabled={busy} onClick={() => void act(async () => { await platform("sdk-keys/" + k.id, "DELETE"); await load(); })}>Revoke key</Button>}</p>)}
      </section></>}
    {tab === "audit" && <section className="section-card"><h2>Workspace activity</h2><p>Individual staff actions and credential-attributed requests.</p>{audit.map(a => <p className="ops-row" key={a.id}><span>{a.action.replaceAll("_", " ")}<small> · {a.actor_id}</small></span><time>{new Date(a.recorded_at).toLocaleString()}</time></p>)}</section>}
  </div></WorkspaceShell>;
}
