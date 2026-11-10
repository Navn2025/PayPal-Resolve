"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import Image from "next/image";
import Link from "next/link";
import { ArrowRight, Mail, ShieldCheck } from "lucide-react";
import { ApiError, dateText } from "@/lib/domain";
import { readJson } from "@/lib/http";
import { Brand, Button, Empty, Notice } from "./ui";

type Entry = { id: string; title: string; order_reference: string | null; merchant_name: string; created_at: string };
type Capabilities = { email_enabled: boolean; google_enabled: boolean };
const root = "/api/customer-account/";
const failureText = (failure: unknown) => failure instanceof Error ? failure.message : "Could not complete this request.";
const googleNotices: Record<string, string> = {
  cancelled: "Google sign-in was cancelled.",
  invalid: "This Google sign-in attempt expired. Try again.",
  email: "Google couldn’t verify ownership of this address. Use an email sign-in link or your private case link.",
  unavailable: "Google sign-in couldn’t finish. Try again or use your private link.",
};

function post<T>(path: string, payload?: object) {
  return fetch(root + path, {
    method: "POST", cache: "no-store",
    ...(payload && { body: JSON.stringify(payload), headers: { "Content-Type": "application/json" } }),
  }).then(readJson<T>);
}

export function CustomerAccount() {
  const [login, setLogin] = useState("");
  const [items, setItems] = useState<Entry[] | null>(null);
  const [status, setStatus] = useState("loading");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);

  const load = useCallback(async () => {
    try {
      setItems(await fetch(root + "cases", { cache: "no-store" }).then(readJson<Entry[]>));
    } catch (failure) {
      if (!(failure instanceof ApiError) || failure.status !== 401) setError(failureText(failure));
      setItems(null);
    } finally { setStatus("ready"); }
  }, []);

  useEffect(() => {
    function readLink() {
      const hash = window.location.hash.slice(1);
      if (!hash) return;
      window.history.replaceState(window.history.state, "", window.location.pathname);
      if (/^rlog_[A-Za-z0-9_-]{43}$/.test(hash)) setLogin(hash);
      else setError("This sign-in link is invalid.");
    }
    const query = new URLSearchParams(window.location.search);
    const googleStatus = query.get("google");
    if (googleStatus) {
      if (Object.hasOwn(googleNotices, googleStatus)) setError(googleNotices[googleStatus]);
      window.history.replaceState(window.history.state, "", window.location.pathname + window.location.hash);
    }
    readLink();
    window.addEventListener("hashchange", readLink);
    void fetch(root + "capabilities", { cache: "no-store" })
      .then(readJson<Capabilities>).then(setCapabilities)
      .catch(() => setCapabilities({ email_enabled: false, google_enabled: false }));
    void load();
    return () => window.removeEventListener("hashchange", readLink);
  }, [load]);

  async function request(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const email = String(new FormData(event.currentTarget).get("email") ?? "").trim();
    setBusy(true); setError(""); setNotice("");
    try {
      await post("request-sign-in", { email });
      setNotice("If there are cases for this email, you’ll receive a sign-in link.");
    } catch (failure) { setError(failureText(failure)); }
    finally { setBusy(false); }
  }
  async function signIn() {
    setBusy(true); setError("");
    try { await post("redeem", { token: login }); setLogin(""); await load(); }
    catch (failure) { setError(failureText(failure)); setLogin(""); }
    finally { setBusy(false); }
  }
  async function signInWithGoogle() {
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await post<{ authorize_url: string }>("google/start");
      window.location.assign(result.authorize_url);
    } catch (failure) { setError(failureText(failure)); setBusy(false); }
  }
  async function open(id: string) {
    setBusy(true); setError("");
    try {
      const result = await post<{ token: string }>("cases/" + id + "/open");
      window.location.assign("/customer#" + result.token);
    } catch (failure) { setError(failureText(failure)); }
    finally { setBusy(false); }
  }
  async function signOut() {
    setBusy(true); setError("");
    try { await post("sign-out"); setItems(null); setNotice("Signed out."); }
    catch (failure) { setError(failureText(failure)); }
    finally { setBusy(false); }
  }
  return <div className="customer-shell">
    <header className="customer-top"><div><Link href="/" className="site-brand" aria-label="Resolve home"><Brand small /></Link><span>Customer portal</span></div><a className="inline-link" href="/customer">Track a case</a></header>
    <main className="customer-main">
      <section className="section-card customer-intake">
        <div className="eyebrow">Customer account</div><h1>My cases</h1>
        {error && <Notice>{error}</Notice>}{notice && <Notice tone="info">{notice}</Notice>}
        {login ? <div className="account-actions"><p>Continue to sign in using the link sent to your email.</p>
          <Button variant="primary" disabled={busy} onClick={signIn}><ShieldCheck size={16} /> Continue to My cases</Button></div>
          : status === "loading" ? <p>Checking your session…</p>
            : items ? <div className="account-actions">
              {items.length ? <ul className="account-cases">{items.map((entry) => <li key={entry.id}>
                <div><strong>{entry.title}</strong><small>{entry.merchant_name}{entry.order_reference ? " · " + entry.order_reference : ""} · {dateText(entry.created_at)}</small></div>
                <Button disabled={busy} onClick={() => void open(entry.id)}>Open case <ArrowRight size={14} /></Button>
              </li>)}</ul> : <Empty title="No cases to show" detail="Open your merchant’s private order invite and submit the issue. Use the same email the merchant associated with that order." />}
              <Button disabled={busy} onClick={signOut}>Sign out</Button>
            </div> : !capabilities ? <p>Loading sign-in options…</p> : <div className="account-actions">
              {capabilities.google_enabled && <>
                <p>Use the Google account that matches the email on your order.</p>
                <button type="button" className="customer-google-button" disabled={busy} onClick={() => void signInWithGoogle()}>
                  <Image src="/google-signin.png" width={177} height={40} alt="Sign in with Google" unoptimized />
                </button>
              </>}
              {capabilities.email_enabled && <form method="post" action={root + "request-sign-in"} onSubmit={request}>
                <label className="field"><span>Email address</span><input name="email" type="email" maxLength={254} required autoComplete="email" /></label>
                <p className="muted">Use the email associated with your order.</p>
                <Button type="submit" variant={capabilities.google_enabled ? "secondary" : "primary"} disabled={busy}><Mail size={16} /> Email me a sign-in link</Button>
              </form>}
              {!capabilities.google_enabled && !capabilities.email_enabled && <p>Open the private link shared by your merchant to see your case.</p>}
            </div>}
      </section>
    </main>
  </div>;
}
