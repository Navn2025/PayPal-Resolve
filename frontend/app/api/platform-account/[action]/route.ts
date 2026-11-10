import { NextRequest } from "next/server";
import { changeSession, error, forward, json, readBody, sameOrigin, session, SESSION_PATTERN } from "@/lib/server";

export async function POST(request: NextRequest, context: { params: Promise<{ action: string }> }) {
  if (!sameOrigin(request)) return error(403, "Open the account form from the configured address.");
  const { action } = await context.params;
  if (!["signup", "login", "accept-invite", "claim"].includes(action)) return error(404, "Account action not found.");
  if (request.headers.get("content-type")?.split(";")[0] !== "application/json") return error(415, "Use a JSON request.");
  const body = await readBody(request);
  if (body === null) return error(413, "Account request is too large.");
  try { JSON.parse(body); } catch { return error(422, "Enter valid account details."); }
  const response = await forward("/platform/account/" + action, action === "claim" ? session(request) : null, "POST", body);
  if (!response.ok) return response;
  const { token, ...account } = await response.json();
  if (typeof token !== "string" || !SESSION_PATTERN.test(token)) return error(502, "The account session could not be created.");
  return changeSession(request, json(account), token);
}
