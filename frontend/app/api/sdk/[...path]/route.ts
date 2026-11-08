import { NextRequest } from "next/server";
import { error, forward, readBody } from "@/lib/server";

const caseId = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
const report = new RegExp("^resolution-cases/" + caseId + "/commerce$", "i");
const refresh = new RegExp("^resolution-cases/" + caseId + "/commerce/refresh$", "i");
const snapshots = new Set(["commerce/orders/register", "commerce/orders/sync"]);
type Context = { params: Promise<{ path: string[] }> };

async function handle(request: NextRequest, context: Context, method: "GET" | "POST") {
  const path = (await context.params).path.join("/");
  const writesSnapshot = method === "POST" && snapshots.has(path);
  if (!(writesSnapshot || (method === "GET" ? report : refresh).test(path))) {
    return error(404, "This action is not available through the SDK gateway.");
  }
  const credential = request.headers.get("authorization")?.match(/^Bearer (rslv_[A-Za-z0-9_-]{43})$/i)?.[1];
  if (!credential) return error(401, "Use the SDK key in your server's Authorization header.");
  if (request.nextUrl.search) return error(400, "This SDK action does not accept query parameters.");
  let body: string | undefined;
  if (method === "POST") {
    const text = await readBody(request);
    if (text === null || new TextEncoder().encode(text).byteLength > 32 * 1024) {
      return error(413, "The SDK request is too large.");
    }
    if (writesSnapshot) {
      if (request.headers.get("content-type")?.split(";")[0].trim().toLowerCase() !== "application/json") {
        return error(415, "Send an application/json snapshot.");
      }
      body = text;
    } else if (text) {
      return error(400, "This SDK action does not accept a body.");
    }
  }
  return forward("/" + path, credential, method, body);
}

export const GET = (request: NextRequest, context: Context) => handle(request, context, "GET");
export const POST = (request: NextRequest, context: Context) => handle(request, context, "POST");
