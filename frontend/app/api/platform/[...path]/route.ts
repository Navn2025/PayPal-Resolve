import { NextRequest } from "next/server";
import { error, forward, readBody, sameOrigin, session } from "@/lib/server";

const id = "[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}";
const provider = "(?:paypal|zendesk|shopify|easypost)";
const rules = {
  GET: [`cases/${id}/returns/${id}/guide`,"me", "return-policy", "team", "audit", "connections", "sdk-keys", "imports", `imports/${id}`, "dashboard", "watchdog",
    `cases/${id}/(?:offers|returns|dispute-packages|support-requests|disputes)`, `cases/${id}/dispute-packages/${id}(?:/export)?`],
  POST: [`cases/${id}/(?:disputes|refund-traces|dispute-documents)`, `cases/${id}/returns/${id}/(?:inspection|labels)`,"team/invites", "sdk-keys", "support-keys", `connections/${provider}/check`, "imports/zendesk", "watchdog/scan",
    `cases/${id}/(?:offers|returns|dispute-packages)`, `cases/${id}/dispute-packages/${id}/review`],
  PUT: ["return-policy", `cases/${id}/returns/${id}/guide`,`team/${id}`, `connections/${provider}`, `imports/${id}/match`, `cases/${id}/returns/${id}`],
  DELETE: [`sdk-keys/${id}`],
};
type Context = { params: Promise<{ path: string[] }> };
type Method = keyof typeof rules;

async function handle(request: NextRequest, context: Context, method: Method) {
  if (method !== "GET" && !sameOrigin(request)) return error(403, "Open this action from your workspace.");
  const token = session(request);
  if (!token) return error(401, "Sign in to your workspace.");
  const path = (await context.params).path.join("/");
  if (request.nextUrl.search || !rules[method].some(pattern => new RegExp(`^(?:${pattern})$`, "i").test(path))) return error(404, "Workspace action not found.");
  let body: string | undefined;
  if (method !== "GET") {
    const raw = await readBody(request, path.endsWith("/labels") ? 3 * 1024 * 1024 : undefined);
    if (raw === null) return error(413, "This request is too large.");
    body = raw;
    if (raw) {
      if (request.headers.get("content-type")?.split(";")[0] !== "application/json") return error(415, "Use a JSON request.");
      try { JSON.parse(raw); } catch { return error(422, "Invalid workspace request."); }
    }
  }
  return forward("/platform/" + path, token, method, body, { download: path.endsWith("/export") });
}
export const GET = (r: NextRequest, c: Context) => handle(r, c, "GET");
export const POST = (r: NextRequest, c: Context) => handle(r, c, "POST");
export const PUT = (r: NextRequest, c: Context) => handle(r, c, "PUT");
export const DELETE = (r: NextRequest, c: Context) => handle(r, c, "DELETE");
