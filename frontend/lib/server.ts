import "server-only";
import { NextRequest, NextResponse } from "next/server";

const SESSION_SECONDS = 8 * 60 * 60;
export const SESSION_COOKIE = "resolve_merchant_session";
export const SESSION_PATTERN = /^rweb_[A-Za-z0-9_-]{43}$/;
const MAX_BODY = 64 * 1024;
export const noStore = { "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex, nofollow" };
const loopback = ["127.0.0.1", "localhost", "[::1]"];

export function json(data: unknown, status = 200) {
  return NextResponse.json(data, { status, headers: noStore });
}
export function error(status: number, detail: string) {
  return json({ detail }, status);
}
export function session(request: NextRequest) {
  const token = request.cookies.get(SESSION_COOKIE)?.value ?? "";
  return SESSION_PATTERN.test(token) ? token : null;
}
export function changeSession(request: NextRequest, response: NextResponse, token?: string) {
  response.cookies.set(SESSION_COOKIE, token ?? "", {
    httpOnly: true, secure: merchantRequestOrigin(request)?.startsWith("https:") ?? false,
    sameSite: "lax", path: "/", maxAge: token ? SESSION_SECONDS : 0,
  });
  return response;
}
function configuredOrigin(value: string | undefined) {
  try {
    const parsed = value ? new URL(value) : null;
    return parsed && !parsed.username && !parsed.password && parsed.pathname === "/" && !parsed.search && !parsed.hash
      && (parsed.protocol === "https:" || (parsed.protocol === "http:" && loopback.includes(parsed.hostname))) ? parsed : null;
  } catch { return null; }
}

export function merchantRequestOrigin(request: NextRequest) {
  const host = request.headers.get("host");
  if (!host) return null;
  const configured = configuredOrigin(process.env.RESOLVE_MERCHANT_WEB_ORIGIN);
  if (configured?.host === host) return configured.origin;
  const local = configuredOrigin(request.nextUrl.protocol + "//" + host);
  return local && local.host === host && loopback.includes(local.hostname) ? local.origin : null;
}

export function sameOrigin(request: NextRequest) {
  const expected = merchantRequestOrigin(request);
  return !!expected && request.headers.get("origin") === expected;
}

export function customerRequestOrigin(request: NextRequest) {
  const expected = configuredOrigin(process.env.RESOLVE_CUSTOMER_PUBLIC_ORIGIN);
  if (expected && request.headers.get("host") === expected.host) return expected.origin;
  return merchantRequestOrigin(request);
}

export function customerSameOrigin(request: NextRequest) {
  const origin = customerRequestOrigin(request);
  return !!origin && request.headers.get("origin") === origin;
}
export async function readBody(request: NextRequest): Promise<string | null> {
  if (!request.body) return "";
  if (Number(request.headers.get("content-length") ?? 0) > MAX_BODY) return null;
  const reader = request.body.getReader();
  const decoder = new TextDecoder();
  let text = "", bytes = 0;
  while (true) {
    const result = await reader.read();
    if (result.done) return text + decoder.decode();
    bytes += result.value.byteLength;
    if (bytes > MAX_BODY) { await reader.cancel(); return null; }
    text += decoder.decode(result.value, { stream: true });
  }
}
export async function readBinary(request: NextRequest, limit: number): Promise<ArrayBuffer | null> {
  if (!request.body) return new ArrayBuffer(0);
  if (Number(request.headers.get("content-length") ?? 0) > limit) return null;
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  while (true) {
    const result = await reader.read();
    if (result.done) break;
    size += result.value.byteLength;
    if (size > limit) { await reader.cancel(); return null; }
    chunks.push(result.value);
  }
  const output = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { output.set(chunk, offset); offset += chunk.length; }
  return output.buffer;
}
export async function forward(path: string, token: string | null, method = "GET", body?: string | ArrayBuffer,
  options?: { headers?: Record<string, string>; download?: boolean }) {
  let origin: string;
  try {
    const endpoint = new URL(process.env.RESOLVE_BACKEND_URL ?? "http://127.0.0.1:8000");
    const allowedHttp = endpoint.protocol === "http:" && (loopback.includes(endpoint.hostname)
      || process.env.RESOLVE_BACKEND_ALLOW_PRIVATE_HTTP === "true");
    if ((!allowedHttp && endpoint.protocol !== "https:")
      || endpoint.username || endpoint.password || endpoint.pathname !== "/" || endpoint.search || endpoint.hash) throw new Error();
    origin = endpoint.origin;
  } catch { return error(503, "The Resolve backend address is not configured."); }
  try {
    const response = await fetch(origin + path, {
      method, redirect: "manual", cache: "no-store", signal: AbortSignal.timeout(60_000),
      headers: { ...(token && { Authorization: "Bearer " + token }), Accept: "application/json", ...(body && { "Content-Type": "application/json" }), ...options?.headers },
      ...(body && { body }),
    });
    if (options?.download && response.ok) {
      return new NextResponse(await response.arrayBuffer(), { headers: {
        ...noStore, "Content-Type": response.headers.get("content-type") ?? "application/octet-stream",
        "Content-Disposition": response.headers.get("content-disposition") ?? "attachment",
        "Content-Security-Policy": "default-src 'none'; sandbox",
      } });
    }
    const data = await response.json().catch(() => null);
    if (data === null || (response.status >= 300 && response.status < 400)) {
      return error(502, "The backend did not return a Resolve API response.");
    }
    return json(data, response.status);
  } catch {
    return error(503, "Could not reach the Resolve backend. Try again shortly.");
  }
}
