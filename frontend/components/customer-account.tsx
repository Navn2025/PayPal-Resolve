"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { ArrowRight, Mail, ShieldCheck } from "lucide-react";
import { ApiError, dateText } from "@/lib/domain";
import { readJson } from "@/lib/http";
import { Brand, Button, Empty, Notice } from "./ui";

type Entry = { id: string; title: string; order_reference: string | null; merchant_name: string; created_at: string };
const root = "/api/customer-account/";
const failureText = (failure: unknown) => failure instanceof Error ? failure.message : "Could not complete this request.";

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
    readLink();
    window.addEventListener("hashchange", readLink);
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
        <div className="eyebrow">CUSTOMER ACCOUNT</div><h1>My cases</h1>
        {error && <Notice>{error}</Notice>}{notice && <Notice tone="info">{notice}</Notice>}
        {login ? <div className="account-actions"><p>Continue to sign in using the link sent to your email.</p>
          <Button variant="primary" disabled={busy} onClick={signIn}><ShieldCheck size={16} /> Continue to My cases</Button></div>
          : status === "loading" ? <p>Checking your session…</p>
            : items ? <div className="account-actions">
              {items.length ? <ul className="account-cases">{items.map((entry) => <li key={entry.id}>
                <div><strong>{entry.title}</strong><small>{entry.merchant_name}{entry.order_reference ? " · " + entry.order_reference : ""} · {dateText(entry.created_at)}</small></div>
                <Button disabled={busy} onClick={() => void open(entry.id)}>Open case <ArrowRight size={14} /></Button>
              </li>)}</ul> : <Empty title="No cases to show" detail="Cases appear here when a merchant sends you an order invite by email and you submit it." />}
              <Button disabled={busy} onClick={signOut}>Sign out</Button>
            </div> : <form onSubmit={request}>
              <label className="field"><span>Email address</span><input name="email" type="email" maxLength={254} required autoComplete="email" /></label>
              <p className="muted">Use the email that received your order invite.</p>
              <Button type="submit" variant="primary" disabled={busy}><Mail size={16} /> {busy ? "Requesting…" : "Email me a sign-in link"}</Button>
            </form>}
      </section>
    </main>
  </div>;
}
