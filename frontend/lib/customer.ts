import type { Outcome, Remedy } from "./domain";
import { readJson } from "./http";

export interface CustomerLink {
  active: boolean;
  expires_at: string | null;
  title: string | null;
  show_order_reference: boolean;
}
export interface IssuedCustomerLink extends CustomerLink { token: string; public_url?: string | null }
export interface Message {
  id: string;
  sender: "customer" | "merchant";
  body: string;
  created_at: string;
}
export interface Evidence {
  id: string; filename: string; content_type: string; size_bytes: number; created_at: string; source: "customer_submitted";
}
export interface CustomerMilestone {
  label: string; occurred_at: string; source: "customer_submitted" | "merchant_recorded" | "provider_confirmed" | "resolve";
}
export interface CustomerNextStep { actor: "customer" | "merchant" | "paypal" | "none"; action: string; due_at: string | null; overdue: boolean }
export type Workflow = "waiting_on_customer" | "needs_approval" | "pending_with_paypal" | "merchant_action" | "resolved";
export interface Operations {
  revision: number; assignee: string | null; due_at: string | null; promise_due_at: string | null;
  overdue: boolean; waiting_on_customer: boolean; workflow: Workflow; next_actor: CustomerNextStep["actor"];
  next_action: string; unread_count: number; message_watermark: number; issue_type: string | null;
}
export interface IntakeInvite { token: string; order_reference: string; expires_at: string; email_queued: boolean; public_url: string | null }
export interface IntakeView { order_reference: string; submitted: boolean }
export const issueLabels: Record<string, string> = {
  missing_item: "Missing item", duplicate_charge: "Duplicate charge", damaged_delivery: "Damaged delivery",
  refund_delay: "Refund delay", other: "Other order issue",
};
export const workflowLabels: Record<Workflow, string> = {
  waiting_on_customer: "Waiting on customer", needs_approval: "Needs approval", pending_with_paypal: "Pending with PayPal",
  merchant_action: "Merchant action", resolved: "Resolved",
};
export interface CustomerCase {
  title: string;
  order_reference: string | null;
  outcome: Outcome;
  expires_at: string;
  promises: { kind: Remedy; promise: string; outcome: Outcome; due_at?: string | null; provider_confirmed: boolean }[];
  refund: { promised_amount: string; confirmed_amount: string | null; pending_amount: string | null; outstanding_amount: string | null; verification: "current" | "unverified"; currency: "USD"; environment: "sandbox" } | null;
  messages: Message[];
  evidence: Evidence[];
  timeline: CustomerMilestone[];
  next_step: CustomerNextStep;
}

export const customerLabels: Record<Outcome, string> = {
  waiting: "In progress", pending: "Awaiting confirmation", needs_review: "Under review", fulfilled: "Resolved",
};
export function customerRequest<T>(action: "view" | "messages" | "intake-view" | "intake", token: string, data?: Record<string, unknown>) {
  return fetch("/api/customer-portal/" + action, {
    method: "POST", credentials: "omit", cache: "no-store", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...data, token }),
  }).then(readJson<T>);
}

export async function uploadCustomerFile(token: string, file: File) {
  const filename = file.name.replace(/[^A-Za-z0-9._ -]/g, "_").replace(/^[^A-Za-z0-9]+/, "evidence");
  return readJson<Evidence>(await fetch("/api/customer-portal/evidence", {
    method: "POST", credentials: "omit", cache: "no-store",
    headers: { "Content-Type": file.type, "X-Customer-Link": token, "X-File-Name": filename },
    body: file,
  }));
}

export async function downloadFile(path: string, filename: string, token?: string) {
  const response = await fetch(path, token ? {
    method: "POST", credentials: "omit", cache: "no-store", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  } : { cache: "no-store", credentials: "same-origin" });
  if (!response.ok) await readJson(response);
  saveBlob(await response.blob(), filename);
}

export function saveBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url; anchor.download = name; anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 500);
}
