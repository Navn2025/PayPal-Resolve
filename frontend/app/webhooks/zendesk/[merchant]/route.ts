import { NextRequest } from "next/server";
import { error, forward, readBinary } from "@/lib/server";
export async function POST(request: NextRequest, context: { params: Promise<{ merchant: string }> }) {
  const { merchant } = await context.params;
  if (!/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(merchant)) return error(404, "Webhook not found.");
  const body = await readBinary(request, 65536);
  if (body === null) return error(413, "Webhook payload is too large.");
  return forward("/webhooks/zendesk/" + merchant, null, "POST", body, { headers: {
    "X-Zendesk-Webhook-Signature": request.headers.get("x-zendesk-webhook-signature") ?? "",
    "X-Zendesk-Webhook-Signature-Timestamp": request.headers.get("x-zendesk-webhook-signature-timestamp") ?? "",
    "X-Zendesk-Webhook-Invocation-Id": request.headers.get("x-zendesk-webhook-invocation-id") ?? "",
  } });
}
