"use client";

import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { ArrowLeft, ArrowRight, ArrowUpRight, Eye, EyeOff, FileCheck2, KeyRound, Link2, LogOut, ShieldCheck, Unlink2 } from "lucide-react";
import { readJson } from "@/lib/http";
import { timeText, type Session } from "@/lib/domain";
import { Brand, Notice } from "./ui";

const notices: Record<string, string> = {
  linked: "PayPal sign-in is linked to this workspace.",
  cancelled: "PayPal sign-in was cancelled.",
  invalid: "This PayPal sign-in link is invalid or expired. Start again.",
  unlinked: "This PayPal account isn’t linked. Sign in with your Resolve access key, then link PayPal in settings.",
  conflict: "This PayPal account is already linked, or the workspace has another linked account.",
  reauth: "Sign in again with a Resolve access key before changing the PayPal link.",
  unavailable: "PayPal sign-in is unavailable. Try again or use your Resolve access key.",
};
const describe = (error: unknown) => error instanceof Error ? error.message : "Could not complete the request. Try again.";
const readSession = () => fetch("/api/session", { cache: "no-store" }).then(readJson<Session>);

async function startPayPal(intent: "signin" | "link") {
  const response = await fetch("/api/auth/paypal/start", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ intent }),
  });
  const result = await readJson<{ authorize_url: string }>(response);
  window.location.assign(result.authorize_url);
}

export function MerchantLogin({ notice, next }: { notice?: string; next: "/workspace" | "/workspace/settings" }) {
  const [session, setSession] = useState<Session | null>(null);
  const [busy, setBusy] = useState<"paypal" | "key" | null>(null);
  const [error, setError] = useState("");
  const [visible, setVisible] = useState(false);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    let active = true;
    setReady(true);
    readSession().then((value) => { if (active) setSession(value); }).catch(() => { if (active) setSession({ merchant: null }); });
    return () => { active = false; };
  }, []);

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const key = String(new FormData(event.currentTarget).get("key") ?? "").trim();
    setBusy("key"); setError("");
    try {
      const response = await fetch("/api/session", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token: key }),
      });
      const result = await readJson<Session>(response);
      if (!result.merchant) throw new Error("Resolve did not return a merchant workspace.");
      window.location.assign(next);
    } catch (failure) { setError(describe(failure)); setBusy(null); }
  }

  async function paypal() {
    setBusy("paypal"); setError("");
    try { await startPayPal("signin"); }
    catch (failure) { setError(describe(failure)); setBusy(null); }
  }

  return <main className="access-shell">
    <div className="access-inner">
      <div className="access-top"><Link href="/" className="site-brand" aria-label="Resolve home"><Brand /></Link>
        <Link className="site-text-link" href="/"><ArrowLeft size={16} /> Back home</Link></div>
      <div className="access-grid">
        <aside className="access-intro">
          <p className="site-kicker"><span /> MERCHANT WORKSPACE</p>
          <h1>Pick up where the payment left off.</h1>
          <p>One inbox for buyer issues, refund approvals, and evidence your team can stand behind.</p>
          <div className="access-intro-foot"><FileCheck2 size={19} /> Review evidence. Track the outcome.</div>
        </aside>
        <section className="access-card" aria-label="Merchant sign in">
          <p className="site-kicker"><span /> WORKSPACE ACCESS</p>
          <h2>Merchant sign in</h2><p>Sign in to your existing Resolve workspace.</p>
          {notice && notices[notice] && !error && <Notice>{notices[notice]}</Notice>}
          {error && <Notice>{error}</Notice>}
          {session?.merchant && <Link className="site-button site-button-primary access-wide" href="/workspace">Continue to workspace <ArrowRight size={17} /></Link>}
          <button type="button" className="site-button paypal-button access-wide" disabled={!session?.paypal_enabled || !!busy} onClick={() => void paypal()}>
            {busy === "paypal" ? "Opening PayPal…" : "Log in with PayPal"}
          </button>
          {session?.paypal_enabled
            ? <p className="access-caption">For linked accounts. Signing in doesn’t move money.{session.paypal_environment === "sandbox" ? " Sandbox sign-in." : ""}</p>
            : session && <p className="access-caption">PayPal sign-in isn’t enabled for this workspace yet.</p>}
          <div className="access-divider"><span />or use an access key<span /></div>
          <form className="access-form" method="post" action="/api/session" onSubmit={signIn}>
            <div className="field"><label htmlFor="resolve-merchant-key">Resolve access key</label><div className="access-key">
              <input id="resolve-merchant-key" name="key" type={visible ? "text" : "password"} autoComplete="off" autoCapitalize="none" spellCheck={false}
                placeholder="rslv_…" maxLength={125} required disabled={!ready || !!busy} />
              <button type="button" title={visible ? "Hide access key" : "Show access key"} aria-label={visible ? "Hide access key" : "Show access key"} onClick={() => setVisible(!visible)}>
                {visible ? <EyeOff size={17} /> : <Eye size={17} />}
              </button>
            </div></div>
            <button type="submit" className="site-button site-button-primary access-wide" disabled={!ready || !!busy}>
              <KeyRound size={17} /> {busy === "key" ? "Signing in…" : "Sign in with access key"} <ArrowRight size={17} />
            </button>
          </form>
          <div className="access-bottom"><Link href="/customer">Looking for your case?</Link><Link href="/demo">Try the demo <ArrowUpRight size={14} /></Link></div>
        </section>
      </div>
    </div>
  </main>;
}

export function MerchantSettings({ notice }: { notice?: string }) {
  const [session, setSession] = useState<Session | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [message, setMessage] = useState(notice && notices[notice] || "");
  const [success, setSuccess] = useState(notice === "linked");
  useEffect(() => {
    let active = true;
    readSession().then((value) => {
      if (!active) return;
      if (!value.merchant) { window.location.replace("/login?next=settings"); return; }
      setSession(value);
    }).catch((failure) => { if (active) setMessage(describe(failure)); });
    return () => { active = false; };
  }, []);

  async function action(kind: "link" | "unlink" | "signout") {
    setBusy(true); setMessage(""); setSuccess(false);
    try {
      if (kind === "link") { await startPayPal("link"); return; }
      const path = kind === "unlink" ? "/api/auth/paypal/link" : "/api/session";
      await fetch(path, { method: "DELETE" }).then(readJson);
      if (kind === "signout") { window.location.assign("/login"); return; }
      setSession(await readSession());
      setMessage("PayPal sign-in was unlinked."); setSuccess(true); setConfirm(false);
    } catch (failure) { setMessage(describe(failure)); }
    finally { setBusy(false); }
  }

  return <main className="access-shell">
    <div className="access-inner settings-inner">
      <div className="access-top"><Link href="/" className="site-brand" aria-label="Resolve home"><Brand /></Link>
        <Link className="site-text-link" href="/workspace"><ArrowLeft size={16} /> Back to inbox</Link></div>
      <section className="access-card settings-card">
        <p className="site-kicker"><span /> MERCHANT WORKSPACE</p><h1>Account settings</h1>
        {message && <Notice tone={success ? "success" : "error"}>{message}</Notice>}
        {session?.merchant ? <>
          <div className="settings-row"><span className="site-preview-icon"><ShieldCheck size={22} /></span>
            <div><h2>{session.merchant.name}</h2><p>Signed in with {session.method === "paypal" ? "PayPal" : "a Resolve access key"}
              {session.expires_at ? " · Session ends " + timeText(session.expires_at) : ""}</p></div></div>
          <div className="settings-provider"><div className="settings-row"><span className="site-preview-icon"><Link2 size={22} /></span>
            <div><h2>PayPal sign-in</h2><p>{!session.paypal_enabled ? "Not configured" : session.paypal_linked
              ? "Linked to this workspace" : "Ready to link"}{session.paypal_environment === "sandbox" ? " · Sandbox" : ""}</p></div></div>
            <p>Use PayPal to sign in to Resolve. Refunds still use the workspace’s configured PayPal connection and require a separate approval.</p>
            {session.paypal_enabled && session.method === "key" && (!session.paypal_linked
              ? <button type="button" className="site-button site-button-primary" disabled={busy} onClick={() => void action("link")}><Link2 size={17} /> Link PayPal</button>
              : confirm ? <div className="settings-confirm">
                <p>Unlinking ends active PayPal sign-ins. You can still use your Resolve access key.</p>
                <div className="site-actions"><button type="button" className="site-button site-button-quiet" disabled={busy} onClick={() => void action("unlink")}>Confirm unlink</button>
                  <button type="button" className="site-button site-button-quiet" disabled={busy} onClick={() => setConfirm(false)}>Cancel</button></div>
              </div> : <button type="button" className="site-button site-button-quiet" disabled={busy} onClick={() => setConfirm(true)}><Unlink2 size={17} /> Unlink PayPal</button>)}
            {session.paypal_enabled && <Link className="site-text-link" href="/login?next=settings">Sign in with an access key again <ArrowRight size={15} /></Link>}
          </div>
          <button type="button" className="site-button site-button-quiet" disabled={busy} onClick={() => void action("signout")}><LogOut size={17} /> Sign out</button>
        </> : <p>{message ? "Reload this page to retry." : "Checking your workspace…"}</p>}
      </section>
    </div>
  </main>;
}
