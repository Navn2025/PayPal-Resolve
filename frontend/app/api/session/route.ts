import { NextRequest } from "next/server";
import { changeSession, error, forward, json, readBody, sameOrigin, session, SESSION_PATTERN } from "@/lib/server";

export async function GET(request: NextRequest) {
  const token = session(request);
  const [account, options] = await Promise.all([
    token ? forward("/merchant-auth/session", token) : null,
    forward("/merchant-auth/capabilities", null),
  ]);
  if (account && !account.ok && account.status !== 401) return account;
  const flags = options.ok ? await options.json() : { paypal_enabled: false, paypal_environment: null };
  const data = account?.ok ? await account.json() : { merchant: null };
  const result = json({ ...data, ...flags });
  return account?.status === 401 ? changeSession(request, result) : result;
}

export async function POST(request: NextRequest) {
  if (!sameOrigin(request)) return error(403, "Open Resolve from the configured address to sign in.");
  let token: unknown;
  try {
    const body = await readBody(request);
    if (body === null) return error(413, "The sign-in request is too large.");
    token = JSON.parse(body).token;
  } catch { return error(400, "Enter a valid Resolve access key."); }
  if (typeof token !== "string" || !/^rslv_[A-Za-z0-9_-]{20,120}$/.test(token)) {
    return error(422, "Enter the access key issued by Resolve.");
  }
  const response = await forward("/merchant-auth/session/key", null, "POST", JSON.stringify({ key: token }));
  if (!response.ok) return response;
  const { token: sessionToken, ...identity } = await response.json();
  if (typeof sessionToken !== "string" || !SESSION_PATTERN.test(sessionToken) || !identity.merchant?.id) {
    return error(502, "Resolve could not start a merchant session.");
  }
  const previous = session(request);
  if (previous) await forward("/merchant-auth/session", previous, "DELETE");
  return changeSession(request, json(identity), sessionToken);
}

export async function DELETE(request: NextRequest) {
  if (!sameOrigin(request)) return error(403, "Sign out from the configured workspace.");
  const token = session(request);
  if (token) {
    const response = await forward("/merchant-auth/session", token, "DELETE");
    if (!response.ok) return response;
  }
  return changeSession(request, json({ merchant: null }));
}
