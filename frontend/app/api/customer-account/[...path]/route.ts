import { NextRequest, NextResponse } from "next/server";
import { customerRequestOrigin, customerSameOrigin, error, forward, json, noStore, readBody } from "@/lib/server";

const cookie = "resolve_customer_session";
const sessionPattern = /^racs_[A-Za-z0-9_-]{43}$/;
const googleCookie = "resolve_google_flow";
const googleCallback = "/api/customer-account/google/callback";
const randomPattern = /^[A-Za-z0-9_-]{43}$/;
const openPath = /^cases\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\/open$/i;
type Context = { params: Promise<{ path: string[] }> };

function sessionToken(request: NextRequest) {
  const token = request.cookies.get(cookie)?.value ?? "";
  return sessionPattern.test(token) ? token : null;
}

function setCookie(request: NextRequest, response: NextResponse, token: string, seconds: number) {
  response.cookies.set(cookie, token, {
    path: "/api/customer-account", httpOnly: true, sameSite: "strict",
    secure: customerRequestOrigin(request)?.startsWith("https:") ?? false,
    maxAge: seconds,
  });
  return response;
}

function googleFlowCookie(request: NextRequest, response: NextResponse, token = "") {
  response.cookies.set(googleCookie, token, {
    path: googleCallback, httpOnly: true, sameSite: "lax",
    secure: customerRequestOrigin(request)?.startsWith("https:") ?? false,
    maxAge: token ? 600 : 0,
  });
  return response;
}

async function googleReturn(request: NextRequest) {
  const origin = customerRequestOrigin(request);
  if (!origin) return error(403, "Open the customer portal from its configured address.");
  const redirect = (notice?: string) => googleFlowCookie(request, NextResponse.redirect(
    origin + "/customer/account" + (notice ? "?google=" + notice : ""),
    { status: 303, headers: noStore },
  ));
  const state = request.nextUrl.searchParams.get("state");
  const code = request.nextUrl.searchParams.get("code");
  const browser = request.cookies.get(googleCookie)?.value;
  if (request.nextUrl.searchParams.has("error")) return redirect("cancelled");
  if (!state || !randomPattern.test(state) || !browser || !randomPattern.test(browser) ||
      !code || !/^[!-~]{1,2048}$/.test(code)) return redirect("invalid");
  const response = await forward("/customer-account/google/finish", null, "POST", JSON.stringify({
    state, code, browser_token: browser,
  }));
  if (!response.ok) {
    return redirect(response.status === 403 ? "email" : response.status === 400 ? "invalid" : "unavailable");
  }
  const data = await response.json();
  if (typeof data.token !== "string" || !sessionPattern.test(data.token)) return redirect("unavailable");
  const previous = sessionToken(request);
  if (previous) await forward("/customer-account/sign-out", previous, "POST");
  return setCookie(request, redirect(), data.token, 7 * 24 * 60 * 60);
}

export async function GET(request: NextRequest, context: Context) {
  const path = (await context.params).path.join("/");
  if (path === "capabilities") return forward("/customer-account/capabilities", null);
  if (path === "google/callback") return googleReturn(request);
  if (path !== "cases") return error(404, "Customer account action not found.");
  const token = sessionToken(request);
  if (!token) return error(401, "Sign in to view your cases.");
  return forward("/customer-account/cases", token);
}

export async function POST(request: NextRequest, context: Context) {
  if (!customerSameOrigin(request)) return error(403, "Open the customer portal from its configured address.");
  const path = (await context.params).path.join("/");
  if (path === "google/start") {
    const response = await forward("/customer-account/google/start", null, "POST");
    if (!response.ok) return response;
    const data = await response.json();
    try {
      const authorize = new URL(data.authorize_url);
      if (authorize.origin !== "https://accounts.google.com" || authorize.username || authorize.password ||
          authorize.pathname !== "/o/oauth2/v2/auth" || !randomPattern.test(data.browser_token) ||
          authorize.searchParams.get("redirect_uri") !== customerRequestOrigin(request) + googleCallback) {
        throw new Error();
      }
      return googleFlowCookie(request, json({ authorize_url: authorize.href }), data.browser_token);
    } catch {
      return error(503, "Google sign-in isn’t configured for this address.");
    }
  }
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
