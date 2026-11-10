"use client";

import { useEffect, useState, type FormEvent } from "react";
import { MerchantSdkKeys } from "./merchant-sdk-keys";
import Link from "next/link";
import { ArrowLeft, ArrowRight, ArrowUpRight, Eye, EyeOff, FileCheck2, KeyRound, Link2, ShieldCheck, Unlink2 } from "lucide-react";
import { readJson } from "@/lib/http";
import { timeText, type Session } from "@/lib/domain";
import { Brand, Button, Notice } from "./ui";
import { WorkspaceShell } from "./workspace-shell";

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
          <h2>Merchant sign in</h2><p>Sign in to your existing Resolve workspace.</p><p><Link href="/account">Use your staff account or create a workspace</Link></p>
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

  async function action(kind: "link" | "unlink") {
    setBusy(true); setMessage(""); setSuccess(false);
    try {
      if (kind === "link") { await startPayPal("link"); return; }
      await fetch("/api/auth/paypal/link", { method: "DELETE" }).then(readJson);
      setSession(await readSession());
      setMessage("PayPal sign-in was unlinked."); setSuccess(true); setConfirm(false);
    } catch (failure) { setMessage(describe(failure)); }
    finally { setBusy(false); }
  }

  const merchant = session?.merchant;
  const paypal = !session?.paypal_enabled ? { label: "Not configured", tone: "badge-pending" }
    : session.paypal_linked ? { label: "Linked", tone: "badge-fulfilled" } : { label: "Ready to link", tone: "badge-waiting" };
  return <WorkspaceShell active="settings" merchant={merchant} contentId="settings-content">
    <div className="workspace-intro"><div><div className="eyebrow intro-eyebrow"><span /> Merchant workspace</div><h1>Account settings</h1>
      <p>Manage how you sign in and which apps can sync orders to this workspace.</p></div></div>
    {message && <Notice tone={success ? "success" : "error"}>{message}</Notice>}
    {!merchant ? <p className="panel-state" role="status">{message ? "Reload this page to retry." : "Checking your workspace…"}</p>
      : <div className="settings-grid">
        <section className="section-card settings-section" aria-labelledby="account-heading">
          <div className="section-head"><div className="settings-title"><span className="section-icon"><ShieldCheck size={20} /></span>
            <div><div className="eyebrow">Account</div><h3 id="account-heading">{merchant.name}</h3></div></div>
            <span className="badge badge-fulfilled"><span />Signed in</span></div>
          <dl className="settings-facts">
            <div><dt>Signed in with</dt><dd>{session.method === "paypal" ? "PayPal" : "Resolve access key"}</dd></div>
            {session.expires_at && <div><dt>Session ends</dt><dd>{timeText(session.expires_at)}</dd></div>}
          </dl>
        </section>
        <section className="section-card settings-section" aria-labelledby="paypal-heading">
          <div className="section-head"><div className="settings-title"><span className="section-icon"><Link2 size={20} /></span>
            <div><div className="eyebrow">Sign-in method</div><h3 id="paypal-heading">PayPal sign-in</h3></div></div>
            <span className="settings-pills">{session.paypal_environment === "sandbox" && <span className="badge badge-pending"><span />Sandbox</span>}
              <span className={`badge ${paypal.tone}`}><span />{paypal.label}</span></span></div>
          <p className="card-note">Use PayPal to sign in to Resolve. Refunds still use the workspace’s configured PayPal connection and require a separate approval.</p>
          {session.paypal_enabled && session.method === "key" && (!session.paypal_linked
            ? <div className="card-actions"><Button variant="primary" disabled={busy} onClick={() => void action("link")}><Link2 size={16} /> Link PayPal</Button></div>
            : confirm ? <div className="settings-confirm">
              <p className="card-note">Unlinking ends active PayPal sign-ins. You can still use your Resolve access key.</p>
              <div className="card-actions"><Button disabled={busy} onClick={() => void action("unlink")}>Confirm unlink</Button>
                <Button variant="ghost" disabled={busy} onClick={() => setConfirm(false)}>Cancel</Button></div>
            </div> : <div className="card-actions"><Button disabled={busy} onClick={() => setConfirm(true)}><Unlink2 size={16} /> Unlink PayPal</Button></div>)}
          {session.paypal_enabled && <Link className="text-link" href="/login?next=settings">Sign in with an access key again <ArrowRight size={15} /></Link>}
        </section>
        <MerchantSdkKeys />
      </div>}
  </WorkspaceShell>;
}
