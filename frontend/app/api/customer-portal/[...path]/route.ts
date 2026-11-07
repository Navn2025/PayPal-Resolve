import { NextRequest } from "next/server";
import { error, forward, readBinary, readBody, customerSameOrigin } from "@/lib/server";

const tokenPattern = /^(rsvp|rint|racp)_[A-Za-z0-9_-]{43}$/;
const fileId = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const types = ["application/pdf", "image/png", "image/jpeg"];

export async function POST(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  if (!customerSameOrigin(request)) return error(403, "Open the customer portal from its configured address.");
  const { path } = await context.params;
  const [action, id] = path;
  if (action === "evidence" && path.length === 1) {
    const token = request.headers.get("x-customer-link") ?? "", name = request.headers.get("x-file-name") ?? "";
    const mime = request.headers.get("content-type")?.split(";")[0] ?? "";
    if (!tokenPattern.test(token)) return error(404, "This customer link is invalid, expired, or revoked.");
    if (!/^[A-Za-z0-9][A-Za-z0-9._ -]{0,119}$/.test(name)) return error(422, "Use a valid evidence filename.");
    if (!types.includes(mime)) return error(415, "Use a PDF, PNG or JPEG evidence file.");
    const content = await readBinary(request, 2 * 1024 * 1024);
    if (content === null) return error(413, "Evidence file exceeds 2 MiB.");
    return forward("/customer-portal/evidence", null, "POST", content, {
      headers: { "Content-Type": mime, "X-Customer-Link": token, "X-File-Name": name },
    });
  }
  const download = action === "evidence" && path.length === 2 && fileId.test(id);
  if (!download && (path.length !== 1 || !["view", "messages", "intake-view", "intake"].includes(action))) return error(404, "Customer portal action not found.");
  if (request.headers.get("content-type")?.split(";")[0] !== "application/json") return error(415, "Use a JSON request.");
  const body = await readBody(request);
  if (body === null) return error(413, "The message is too large.");
  try {
    const input = JSON.parse(body);
    if (typeof input?.token !== "string" || !tokenPattern.test(input.token)) {
      return error(404, "This customer link is invalid, expired, or revoked.");
    }
  } catch { return error(422, "Enter a valid customer portal request."); }
  return forward("/customer-portal/" + path.join("/"), null, "POST", body, { download });
}
