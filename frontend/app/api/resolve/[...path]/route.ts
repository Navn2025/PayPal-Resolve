import { NextRequest } from "next/server";
import { error, forward, readBody, sameOrigin, session } from "@/lib/server";

const id = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
const rules = {
  GET: [
    `resolution-cases/${id}/investigations`,
    "merchant-auth/commerce-keys", "commerce/orders", `commerce/orders/${id}`,
    "resolution-cases", "resolution-cases/inbox", "resolution-cases/promise-health", `resolution-cases/${id}(?:/(?:timeline|evidence-bundle|commerce|customer-link|customer-messages|operations|helpdesk|promise-health|next-action|customer-evidence(?:/${id})?))?`,
    "cases", `cases/${id}(?:/(?:reconciliation|refund-approvals|refund-executions))?`,
    "review-queue",
    "ai/usage",
  ],
  POST: [
    `resolution-cases/${id}/investigations/${id}/review`,
    "merchant-auth/commerce-keys",
    `commerce/orders/${id}/case`, `resolution-cases/${id}/commerce/refresh`,
    "resolution-cases", "resolution-cases/intake-invites", `resolution-cases/${id}/promises(?:/${id}/(?:refresh|evidence))?`,
    `resolution-cases/${id}/(?:customer-link|customer-messages)`,
    `resolution-cases/${id}/operations/read`,
    "cases", `cases/${id}/(?:refund-approvals|refund-executions)`,
    `cases/${id}/refund-executions/${id}/refresh`,
    `review-queue/${id}/resolve`,
    `resolution-cases/${id}/ai/extract-promises`, `resolution-cases/${id}/ai/explain-next-action`,
  ],
  PUT: [`resolution-cases/${id}/promises/${id}`, `resolution-cases/${id}/(?:operations|payment-link|helpdesk)`],
  DELETE: [`merchant-auth/commerce-keys/${id}`, `resolution-cases/${id}/customer-link`],
};
type Context = { params: Promise<{ path: string[] }> };
type Method = keyof typeof rules;

async function handle(request: NextRequest, context: Context, method: Method) {
  if (method !== "GET" && !sameOrigin(request)) return error(403, "The action must come from the configured workspace.");
  const credentials = session(request);
  if (!credentials) return error(401, "Connect a merchant account to use this action.");
  const path = (await context.params).path.join("/");
  if (!rules[method].some((pattern) => new RegExp(`^(?:${pattern})$`, "i").test(path))) {
    return error(404, "This action is not available in the workspace.");
  }
  const query = new URLSearchParams();
  for (const [key, value] of request.nextUrl.searchParams) {
    const max = ["resolution-cases/inbox", "commerce/orders"].includes(path) && key === "q" ? 160
      : path === "commerce/orders" && key === "source" ? 64
        : path === "commerce/orders" && key === "offset" ? 16
      : path === "resolution-cases/inbox" && key === "filter_by" ? 24
        : ["limit", "offset", "status"].includes(key) ? 12 : 0;
    if (method !== "GET" || !max || query.has(key) || value.length > max) {
      return error(400, "Unsupported workspace query.");
    }
    query.set(key, value);
  }
  let body: string | undefined;
  if (method !== "GET") {
    const text = await readBody(request);
    if (text === null) return error(413, "This action is too large.");
    body = text;
    if (body) {
      if (request.headers.get("content-type")?.split(";")[0] !== "application/json") return error(415, "Use a JSON request.");
      try { JSON.parse(body); } catch { return error(400, "Invalid JSON request."); }
    }
  }
  return forward("/" + path + (query.size ? "?" + query.toString() : ""), credentials, method, body,
    { download: method === "GET" && new RegExp(`/customer-evidence/${id}$`, "i").test(path) });
}

export const GET = (request: NextRequest, context: Context) => handle(request, context, "GET");
export const POST = (request: NextRequest, context: Context) => handle(request, context, "POST");
export const PUT = (request: NextRequest, context: Context) => handle(request, context, "PUT");
export const DELETE = (request: NextRequest, context: Context) => handle(request, context, "DELETE");
