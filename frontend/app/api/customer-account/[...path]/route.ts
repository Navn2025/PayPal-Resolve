import { NextRequest, NextResponse } from "next/server";
import { customerSameOrigin, error, forward, json, readBody } from "@/lib/server";

const cookie = "resolve_customer_session";
const sessionPattern = /^racs_[A-Za-z0-9_-]{43}$/;
const openPath = /^cases\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\/open$/i;
type Context = { params: Promise<{ path: string[] }> };

function sessionToken(request: NextRequest) {
  const token = request.cookies.get(cookie)?.value ?? "";
  return sessionPattern.test(token) ? token : null;
}

function setCookie(request: NextRequest, response: NextResponse, token: string, seconds: number) {
  response.cookies.set(cookie, token, {
    path: "/api/customer-account", httpOnly: true, sameSite: "strict",
    secure: request.nextUrl.protocol === "https:" || !!request.headers.get("origin")?.startsWith("https:"),
    maxAge: seconds,
  });
  return response;
}

export async function GET(request: NextRequest, context: Context) {
  const path = (await context.params).path.join("/");
  if (path !== "cases") return error(404, "Customer account action not found.");
  const token = sessionToken(request);
  if (!token) return error(401, "Sign in to view your cases.");
  return forward("/customer-account/cases", token);
}

export async function POST(request: NextRequest, context: Context) {
  if (!customerSameOrigin(request)) return error(403, "Open the customer portal from its configured address.");
  const path = (await context.params).path.join("/");
  if (path === "request-sign-in" || path === "redeem") {
    if (request.headers.get("content-type")?.split(";")[0] !== "application/json") return error(415, "Use a JSON request.");
    const body = await readBody(request);
    if (body === null) return error(413, "Request is too large.");
    try { JSON.parse(body); } catch { return error(422, "Enter a valid account request."); }
    const response = await forward("/customer-account/" + path, null, "POST", body);
    if (!response.ok || path !== "redeem") return response;
    const result = await response.json();
    if (typeof result.token !== "string" || !sessionPattern.test(result.token)) return error(502, "Could not start your session.");
    return setCookie(request, json({ signed_in: true }), result.token, 7 * 24 * 60 * 60);
  }
  if (path !== "sign-out" && !openPath.test(path)) return error(404, "Customer account action not found.");
  const token = sessionToken(request);
  if (!token) return error(401, "Sign in to view your cases.");
  const response = await forward("/customer-account/" + path, token, "POST");
  return path === "sign-out" && response.ok ? setCookie(request, response, "", 0) : response;
}
