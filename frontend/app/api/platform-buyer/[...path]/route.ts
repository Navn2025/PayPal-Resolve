import { NextRequest } from "next/server";
import { customerSameOrigin, error, forward, readBody } from "@/lib/server";

export async function POST(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  if (!customerSameOrigin(request)) return error(403, "Open this action from your private case link.");
  const action = (await context.params).path.join("/");
  if (!["offers", "decision", "returns", "returns/request", "return-policy", "assurance", "returns/guide", "returns/label"].includes(action)) return error(404, "Buyer action not found.");
  if (request.headers.get("content-type")?.split(";")[0] !== "application/json") return error(415, "Use a JSON request.");
  const body = await readBody(request);
  if (body === null) return error(413, "Buyer request is too large.");
  try {
    const data = JSON.parse(body);
    if (!/^(rsvp|rint|racp)_[A-Za-z0-9_-]{43}$/.test(data.token ?? "")) return error(404, "Your case link is invalid or expired.");
  } catch { return error(422, "Enter a valid buyer request."); }
  return forward("/platform/buyer/" + action, null, "POST", body);
}
