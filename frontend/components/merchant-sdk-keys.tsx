"use client";

import Link from "next/link";
import { Copy, KeyRound, Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { backendRequest } from "@/lib/http";
import { timeText } from "@/lib/domain";
import { Notice } from "./ui";

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

  async function copy() {
    if (!issued) return;
    try {
      await navigator.clipboard.writeText(issued.setup);
      setMessage("Copied. Paste this into your app server’s environment.");
    } catch {
      setError("Select the setup text and copy it manually.");
    }
  }

  return <section id="sdk-keys" className="settings-provider sdk-keys" aria-labelledby="sdk-keys-heading">
    <div className="settings-row"><span className="site-preview-icon"><KeyRound size={22} /></span>
      <div><h2 id="sdk-keys-heading">SDK keys</h2><p>Connect a store or app to this merchant workspace.</p></div></div>
    <p>SDK keys let your app sync orders and check their evidence. They cannot sign in to the dashboard or move money.</p>
    {error && <Notice>{error}</Notice>}
    {message && <Notice tone="success">{message}</Notice>}
    {list && !list.can_manage
      ? <p><Link className="site-text-link" href="/login?next=settings">Sign in again with a Resolve access key</Link> to generate or revoke SDK keys.</p>
      : <button type="button" className="site-button site-button-primary" disabled={busy || !list || !!issued} onClick={() => void act()}>
        <Plus size={17} /> Generate SDK key
      </button>}
    {!list && error && <button type="button" className="site-button site-button-quiet" onClick={() => void load()}>Reload keys</button>}
    {issued && <div className="settings-confirm sdk-setup">
      <h3>Copy your server setup</h3>
      <p>Resolve shows this key once. Paste these values into your app server’s environment, then hide the key.</p>
      <textarea aria-label="SDK server environment" readOnly rows={3} spellCheck={false} value={issued.setup} onFocus={(event) => event.currentTarget.select()} />
      <div className="site-actions"><button type="button" className="site-button site-button-primary" onClick={() => void copy()}><Copy size={16} /> Copy SDK setup</button>
        <button type="button" className="site-button site-button-quiet" onClick={() => setIssued(null)}>Hide key</button></div>
    </div>}
    <div className="sdk-key-example">
      <h3>Send an order from your server</h3>
      <pre><code>{'import { createResolve } from "@resolve-paypal/sdk";\n\nawait createResolve().syncOrder({ id: "ORDER-123", status: "paid" });'}</code></pre>
    </div>
    {!!list?.keys.length && <ul className="sdk-key-list" aria-label="Active SDK keys">{list.keys.map((key) => (
      <li key={key.key_id}>
        <div><strong>SDK key · {key.key_id.slice(0, 8)}</strong><p>Created {timeText(key.created_at)}</p></div>
        {revokeId === key.key_id ? <div className="sdk-revoke">
          <span>Your app will need a new key.</span>
          <button type="button" className="site-button site-button-quiet" disabled={busy || !list.can_manage} onClick={() => void act(key.key_id)}>Confirm revoke</button>
          <button type="button" className="site-button site-button-quiet" onClick={() => setRevokeId(null)}>Cancel</button>
        </div> : <button type="button" className="site-button site-button-quiet" aria-label={"Revoke SDK key " + key.key_id.slice(0, 8)}
          disabled={busy || !list.can_manage} onClick={() => setRevokeId(key.key_id)}><Trash2 size={15} /> Revoke</button>}
      </li>
    ))}</ul>}
  </section>;
}
