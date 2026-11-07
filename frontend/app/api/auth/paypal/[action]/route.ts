import { NextRequest, NextResponse } from "next/server";
import { changeSession, error, forward, json, merchantRequestOrigin, noStore, readBody, sameOrigin, session, SESSION_PATTERN } from "@/lib/server";

const flowCookie = "resolve_paypal_flow";
const flowPath = "/api/auth/paypal/callback";
const flowPattern = /^(signin|link)\.([A-Za-z0-9_-]{43})$/;
type Context = { params: Promise<{ action: string }> };

function flow(request: NextRequest, response: NextResponse, value = "") {
  response.cookies.set(flowCookie, value, {
    httpOnly: true, secure: merchantRequestOrigin(request)?.startsWith("https:") ?? false,
    sameSite: "lax", path: flowPath, maxAge: value ? 600 : 0,
  });
  return response;
}

export async function POST(request: NextRequest, context: Context) {
  if ((await context.params).action !== "start") return error(404, "PayPal action not found.");
  if (!sameOrigin(request)) return error(403, "Open the configured workspace to continue.");
  let intent: unknown;
  try {
    const body = await readBody(request);
    if (body === null) return error(413, "The sign-in request is too large.");
    intent = JSON.parse(body).intent;
  } catch { return error(422, "Enter a valid PayPal sign-in request."); }
  if (intent !== "signin" && intent !== "link") return error(422, "Enter a valid PayPal sign-in request.");
  const token = session(request);
  if (intent === "link" && !token) return error(401, "Sign in with an access key first.");
  const response = await forward("/merchant-auth/paypal/start", token, "POST", JSON.stringify({ intent }));
  if (!response.ok) return response;
  const data = await response.json();
  try {
    const url = new URL(data.authorize_url);
    if (url.protocol !== "https:" || !["www.paypal.com", "www.sandbox.paypal.com"].includes(url.host)
      || url.pathname !== "/connect" || url.username || url.password || !/^[A-Za-z0-9_-]{43}$/.test(data.browser_token ?? "")) throw new Error();
    if (url.searchParams.get("redirect_uri") !== merchantRequestOrigin(request) + flowPath) {
      return error(409, "Open the configured PayPal return address to sign in.");
    }
    return flow(request, json({ authorize_url: url.href }), intent + "." + data.browser_token);
  } catch { return error(502, "Resolve could not start PayPal sign-in."); }
}

export async function GET(request: NextRequest, context: Context) {
  if ((await context.params).action !== "callback") return error(404, "PayPal action not found.");
  const origin = merchantRequestOrigin(request);
  if (!origin) return error(403, "This PayPal return address is not configured.");
  const match = flowPattern.exec(request.cookies.get(flowCookie)?.value ?? "");
  const intent = match?.[1] ?? "signin";
  function redirect(path: string) {
    return flow(request, new NextResponse(null, { status: 303, headers: { ...noStore, Location: new URL(path, origin!).href } }));
  }
  const returnPage = intent === "link" ? "/workspace/settings" : "/login";
  const parameters = request.nextUrl.searchParams;
  const state = parameters.get("state") ?? "", code = parameters.get("code") ?? "";
  if (parameters.has("error")) return redirect(returnPage + "?paypal=cancelled");
  if (!match || parameters.getAll("code").length !== 1 || parameters.getAll("state").length !== 1
    || !/^[A-Za-z0-9_-]{43}$/.test(state) || !/^[!-~]{1,2048}$/.test(code)) return redirect(returnPage + "?paypal=invalid");
  const token = session(request);
  const response = await forward("/merchant-auth/paypal/finish", token, "POST",
    JSON.stringify({ state, code, browser_token: match[2] }));
  if (!response.ok) {
    const notice = response.status === 403 ? (intent === "link" ? "reauth" : "unlinked")
      : response.status === 409 ? "conflict" : response.status === 503 ? "unavailable" : "invalid";
    return redirect(returnPage + "?paypal=" + notice);
  }
  const result = await response.json();
  if (intent === "link" && result.intent === "link") return redirect("/workspace/settings?paypal=linked");
  if (intent !== "signin" || result.intent !== "signin" || !SESSION_PATTERN.test(result.session?.token ?? "")) {
    return redirect(returnPage + "?paypal=invalid");
  }
  if (token) await forward("/merchant-auth/session", token, "DELETE");
  return changeSession(request, redirect("/workspace"), result.session.token);
}

export async function DELETE(request: NextRequest, context: Context) {
  if ((await context.params).action !== "link") return error(404, "PayPal action not found.");
  if (!sameOrigin(request)) return error(403, "Open the configured workspace to continue.");
  const token = session(request);
  if (!token) return error(401, "Sign in with an access key first.");
  return forward("/merchant-auth/paypal/link", token, "DELETE");
}
