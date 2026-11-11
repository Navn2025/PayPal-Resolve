"use client";

import { useState } from "react";
import { Check, Copy, Printer } from "lucide-react";

export function DocCode({ language, text }: { language: string; text: string }) {
  const [state, setState] = useState<"idle" | "copied" | "manual">("idle");
  async function copy() {
    try { await navigator.clipboard.writeText(text); setState("copied"); }
    catch { setState("manual"); }
  }
  return <div className="docs-code"><div className="docs-code-toolbar"><span>{language}</span>
    <button type="button" onClick={() => void copy()}>{state === "copied" ? <Check size={14} /> : <Copy size={14} />}{state === "copied" ? "Copied" : "Copy code"}</button>
  </div><pre tabIndex={0} aria-label={`${language} example`}><code>{text}</code></pre>
    <span className="docs-code-status" role="status">{state === "copied" ? "Code copied to clipboard." : state === "manual" ? "Select the code and copy it manually." : ""}</span>
  </div>;
}
export function PrintArticle() {
  return <button className="docs-print" type="button" onClick={() => window.print()}><Printer size={15} />Print article</button>;
}
