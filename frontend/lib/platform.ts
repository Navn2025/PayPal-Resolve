import { readJson } from "./http";

export async function platform<T>(path: string, method = "GET", data?: unknown): Promise<T> {
  const response = await fetch("/api/platform/" + path, {
    method, cache: "no-store", ...(data !== undefined && { headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) }),
  });
  if (response.status === 401) window.location.assign("/account");
  return readJson<T>(response);
}
export async function buyerAction<T>(action: string, token: string, data?: object): Promise<T> {
  return readJson<T>(await fetch("/api/platform-buyer/" + action, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...data, token }) }));
}
export const failureText = (failure: unknown) => failure instanceof Error ? failure.message : "The action could not be completed.";
export interface ReturnItem { product_id: string; name?: string | null; quantity: number; available_quantity: number }
export interface ReturnOrder { id: string; order_reference: string; items: ReturnItem[] }
export interface ReturnRecord { id: string; revision: number; status: string; reason: string; items: { product_id: string; quantity: number }[]; tracking?: { carrier: string; tracking_code: string } | null; replacement?: { carrier: string; tracking_code: string } | null }
export interface ReturnCatalog { orders: ReturnOrder[]; items: ReturnRecord[] }
