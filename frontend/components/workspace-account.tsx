"use client";
import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";
import { Brand, Button, Notice } from "./ui";
import { readJson } from "@/lib/http";
import { failureText } from "@/lib/platform";

export function WorkspaceAccount() {
  const [mode, setMode] = useState("login");
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    setReady(true);
    const invite = window.location.hash.slice(1);
    if (new URLSearchParams(window.location.search).get("claim") === "1") setMode("claim");
    if (/^rinv_[A-Za-z0-9_-]{43}$/.test(invite)) { setToken(invite); setMode("accept-invite"); }
  }, []);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!ready || busy) return;
    const values = Object.fromEntries(new FormData(event.currentTarget));
    setBusy(true); setError("");
    try {
      await readJson(await fetch("/api/platform-account/" + mode, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...values, ...(mode === "accept-invite" && { token }) }) }));
      window.location.assign("/workspace/operations");
    } catch (failure) { setError(failureText(failure)); setBusy(false); }
  }
  return <main className="access-shell"><div className="access-inner"><Link href="/" className="site-brand"><Brand /></Link>
    <section className="section-card ops-account"><p className="eyebrow">YOUR WORKSPACE</p><h1>{mode === "signup" ? "Create your merchant workspace" : mode === "claim" ? "Set up your owner account" : mode === "accept-invite" ? "Join your team" : "Sign in to your workspace"}</h1>
      {!["claim", "accept-invite"].includes(mode) && <div className="filters"><button onClick={() => setMode("login")} aria-pressed={mode === "login"}>Sign in</button><button onClick={() => setMode("signup")} aria-pressed={mode === "signup"}>Create workspace</button></div>}
      {error && <Notice>{error}</Notice>}
      <form className="ops-form" method="post" action={"/api/platform-account/" + mode} onSubmit={submit}>
        <fieldset disabled={!ready || busy} style={{ border: 0, padding: 0, margin: 0, minWidth: 0, display: "contents" }}>
        {mode === "signup" && <label>Store or business name<input name="workspace" maxLength={100} required autoComplete="organization" /></label>}
        {mode !== "login" && <label>Your name<input name="name" maxLength={100} required autoComplete="name" /></label>}
        <label>Email<input type="email" name="email" maxLength={254} required autoComplete="username" /></label>
        <label>Password<input aria-label="Password" type="password" name="password" minLength={12} maxLength={256} required autoComplete={mode === "login" ? "current-password" : "new-password"} /><small>At least 12 characters.</small></label>
        <Button type="submit" variant="primary" disabled={!ready || busy}>{busy ? "Opening workspace…" : mode === "signup" ? "Create workspace" : mode === "accept-invite" ? "Accept invitation" : "Sign in"}</Button>
        </fieldset>
      </form><p><Link href="/login">Use PayPal or a merchant access key</Link></p>
    </section></div></main>;
}
