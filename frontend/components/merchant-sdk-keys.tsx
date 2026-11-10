"use client";

import Link from "next/link";
import { Copy, KeyRound, Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { backendRequest } from "@/lib/http";
import { timeText } from "@/lib/domain";
import { Button, Notice } from "./ui";

type KeyRow = { key_id: string; created_at: string };
type Keys = { keys: KeyRow[]; can_manage: boolean };
type NewKey = { key_id: string; api_key: string };

const path = "/merchant-auth/commerce-keys";
const detail = (error: unknown) => error instanceof Error ? error.message : "Try again shortly.";

export function MerchantSdkKeys() {
  const [list, setList] = useState<Keys | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [issued, setIssued] = useState<{ id: string; setup: string } | null>(null);
  const [revokeId, setRevokeId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try { setList(await backendRequest<Keys>(path)); }
    catch (failure) { setError(detail(failure)); }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function act(id?: string) {
    if (busy) return;
    setBusy(true); setError(""); setMessage("");
    try {
      if (id) {
        await backendRequest(path + "/" + id, "DELETE");
        if (issued?.id === id) setIssued(null);
        setRevokeId(null);
        setMessage("SDK key revoked.");
      } else {
        const key = await backendRequest<NewKey>(path, "POST");
        setIssued({
          id: key.key_id,
          setup: [
            "RESOLVE_API_URL=" + window.location.origin + "/api/sdk",
            "RESOLVE_API_KEY=" + key.api_key,
            "RESOLVE_APP_SOURCE=my-app",
          ].join("\n"),
        });
      }
      await load();
    } catch (failure) {
      setError(detail(failure));
      await load();
    } finally { setBusy(false); }
  }

  const example = 'import { createResolve } from "@resolve-paypal/sdk";\n\nawait createResolve().syncOrder({ id: "ORDER-123", status: "paid" });';
  async function copy(text: string, done: string) {
    try {
      await navigator.clipboard.writeText(text);
      setError(""); setMessage(done);
    } catch {
      setError("Select the text and copy it manually.");
    }
  }

  const count = list?.keys.length ?? 0;
  return <section id="sdk-keys" className="section-card settings-section sdk-keys" aria-labelledby="sdk-keys-heading">
    <div className="section-head"><div className="settings-title"><span className="section-icon"><KeyRound size={20} /></span>
      <div><div className="eyebrow">Connected apps</div><h3 id="sdk-keys-heading">SDK keys</h3></div></div>
      {list && <span className={`badge ${count ? "badge-fulfilled" : "badge-pending"}`}><span />{count ? `${count} active` : "Not configured"}</span>}</div>
    <p className="card-note">Connect a store or app to this merchant workspace. SDK keys let your app sync orders and check their evidence. They cannot sign in to the dashboard or move money.</p>
    {error && <Notice>{error}</Notice>}
    {message && <Notice tone="success">{message}</Notice>}
    {!list && !error && <p className="panel-state" role="status">Loading SDK keys…</p>}
    {list && !list.can_manage
      ? <p className="card-note"><Link className="text-link" href="/login?next=settings">Sign in again with a Resolve access key</Link> to generate or revoke SDK keys.</p>
      : <div className="card-actions"><Button variant="primary" disabled={busy || !list || !!issued} onClick={() => void act()}>
        <Plus size={16} /> Generate SDK key
      </Button></div>}
    {!list && error && <div className="card-actions"><Button onClick={() => void load()}>Reload keys</Button></div>}
    {issued && <div className="sdk-setup">
      <h4>Copy your server setup</h4>
      <p className="card-note">Resolve shows this key once. Paste these values into your app server’s environment, then hide the key.</p>
      <textarea aria-label="SDK server environment" readOnly rows={3} spellCheck={false} value={issued.setup} onFocus={(event) => event.currentTarget.select()} />
      <div className="card-actions"><Button variant="primary" onClick={() => void copy(issued.setup, "Copied. Paste this into your app server’s environment.")}><Copy size={16} /> Copy SDK setup</Button>
        <Button onClick={() => setIssued(null)}>Hide key</Button></div>
    </div>}
    <div className="sdk-key-example">
      <div className="code-head"><h4>Send an order from your server</h4>
        <Button className="small-button" aria-label="Copy example code" onClick={() => void copy(example, "Example code copied.")}><Copy size={14} /> Copy</Button></div>
      <div className="code-block"><pre><code>{example}</code></pre></div>
    </div>
    {list && (count ? <ul className="sdk-key-list" aria-label="Active SDK keys">{list.keys.map((key) => (
      <li key={key.key_id}>
        <div><strong>SDK key · {key.key_id.slice(0, 8)}</strong><p className="card-note">Created {timeText(key.created_at)}</p></div>
        {revokeId === key.key_id ? <div className="sdk-revoke">
          <span>Your app will need a new key.</span>
          <Button className="small-button" disabled={busy || !list.can_manage} onClick={() => void act(key.key_id)}>Confirm revoke</Button>
          <Button variant="ghost" className="small-button" onClick={() => setRevokeId(null)}>Cancel</Button>
        </div> : <Button className="small-button" aria-label={"Revoke SDK key " + key.key_id.slice(0, 8)}
          disabled={busy || !list.can_manage} onClick={() => setRevokeId(key.key_id)}><Trash2 size={15} /> Revoke</Button>}
      </li>
    ))}</ul> : <p className="panel-state">No SDK keys yet.</p>)}
  </section>;
}
