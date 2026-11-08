import { money, ShopError } from "./catalog.mjs";

export const SANDBOX = "https://api-m.sandbox.paypal.com";
const providerID = /^[A-Za-z0-9]{1,64}$/;

function cents(value) {
  if (typeof value !== "string" || !/^\d{1,8}(\.\d{1,2})?$/.test(value)) return null;
  const [whole, fraction = ""] = value.split(".");
  return Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
}

class PayPalError extends ShopError {
  constructor(status, message) {
    super(status, message);
  }
}

export function sandboxApproval(value, id) {
  try {
    const url = new URL(value);
    if (url.protocol === "https:" && ["www.sandbox.paypal.com", "sandbox.paypal.com"].includes(url.hostname) &&
        !url.port && !url.username && !url.password && url.searchParams.get("token") === id) return url.href;
  } catch {
    // An invalid or unexpected provider link must never reach the browser.
  }
  throw new PayPalError(502, "PayPal did not provide a usable Sandbox approval link.");
}

export class SandboxPayPal {
  #auth;
  #seller;
  #token;
  #expires = 0;

  constructor(id, secret, seller) {
    this.#auth = "Basic " + Buffer.from(id + ":" + secret, "utf8").toString("base64");
    this.#seller = seller;
  }

  async #json(path, options, hint) {
    let response;
    try {
      response = await fetch(SANDBOX + path, {
        ...options, redirect: "error", signal: AbortSignal.timeout(12_000),
      });
    } catch {
      throw new PayPalError(502, hint);
    }
    if (!response.ok) {
      await response.body?.cancel();
      throw new PayPalError(response.status === 422 ? 409 : 502, hint);
    }
    try {
      const data = await response.json();
      if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error();
      return data;
    } catch {
      throw new PayPalError(502, hint);
    }
  }

  async #accessToken() {
    if (this.#token && Date.now() < this.#expires) return this.#token;
    const response = await this.#json("/v1/oauth2/token", {
      method: "POST",
      headers: { Authorization: this.#auth, "Content-Type": "application/x-www-form-urlencoded" },
      body: "grant_type=client_credentials",
    }, "PayPal Sandbox authentication failed. Check the seller app settings.");
    if (response.token_type !== "Bearer" || typeof response.access_token !== "string" ||
        !response.access_token || !Number.isFinite(response.expires_in)) {
      throw new PayPalError(502, "PayPal Sandbox did not return a valid access token.");
    }
    this.#token = response.access_token;
    this.#expires = Date.now() + Math.max(0, response.expires_in - 60) * 1000;
    return this.#token;
  }

  async #orders(path, method, requestId, body) {
    const token = await this.#accessToken();
    return this.#json("/v2/checkout/orders" + path, {
      method,
      headers: {
        Authorization: "Bearer " + token, Accept: "application/json",
        ...(requestId ? { "PayPal-Request-Id": requestId, Prefer: "return=representation" } : {}),
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    }, method === "POST" && path.endsWith("/capture")
      ? "PayPal did not confirm this capture. Reopen this receipt to check or retry the same payment."
      : "PayPal Sandbox could not prepare or read this order. Try again.");
  }

  async create(order, origin) {
    const back = new URL("/", origin);
    back.searchParams.set("order", order.id);
    back.searchParams.set("checkout", "approved");
    const cancel = new URL(back);
    cancel.searchParams.set("checkout", "cancelled");
    const result = await this.#orders("", "POST", order.create_key, {
      intent: "CAPTURE",
      purchase_units: [{
        reference_id: order.id,
        description: "Field Brew Supply - Sandbox order",
        amount: { currency_code: "USD", value: money(order.total) },
        payee: { merchant_id: this.#seller },
      }],
      payment_source: { paypal: { experience_context: {
        return_url: back.href, cancel_url: cancel.href, user_action: "PAY_NOW",
        shipping_preference: "NO_SHIPPING",
      } } },
    });
    if (!providerID.test(result.id ?? "")) throw new PayPalError(502, "PayPal did not return a valid order ID.");
    const href = Array.isArray(result.links)
      ? result.links.find(link => link?.rel === "payer-action" || link?.rel === "approve")?.href : null;
    return { id: result.id, approval: sandboxApproval(href, result.id) };
  }

  #captureDetails(result, order) {
    const unit = result.purchase_units?.[0];
    const captures = unit?.payments?.captures;
    if (result.id !== order.paypal_order || result.purchase_units?.length !== 1 ||
        unit?.reference_id !== order.id || unit?.payee?.merchant_id !== this.#seller ||
        captures?.length !== 1 || !providerID.test(captures[0]?.id ?? "") ||
        captures[0]?.amount?.currency_code !== "USD" ||
        cents(captures[0]?.amount?.value) !== order.total ||
        !["COMPLETED", "PENDING"].includes(captures[0].status)) {
      throw new PayPalError(502, "The PayPal capture could not be matched to this store order. Review the order before retrying.");
    }
    return { id: captures[0].id, state: captures[0].status.toLowerCase() };
  }

  async capture(order) {
    const path = "/" + order.paypal_order;
    // Read first so a prior successful submission is recovered even after a lost response.
    const current = await this.#orders(path, "GET");
    if (current.status === "COMPLETED" || current.purchase_units?.[0]?.payments?.captures?.length) {
      return this.#captureDetails(current, order);
    }
    if (order.capture_id) {
      throw new PayPalError(502, "The previously recorded capture is not visible yet. Try reading the receipt again.");
    }
    if (current.status !== "APPROVED") throw new PayPalError(409, "Approve the order with your PayPal Sandbox buyer first.");
    if (Date.now() - order.created_at > 30 * 60 * 1000) {
      throw new PayPalError(409, "This checkout window has expired. Review the PayPal order before starting a new checkout.");
    }
    const payment = await this.#orders(path + "/capture", "POST", order.capture_key, {});
    // Some representations omit payee or reference_id; independently read the
    // original order before projecting a captured payment into the store.
    const capture = payment.purchase_units?.[0];
    return this.#captureDetails(
      capture?.payee?.merchant_id && capture?.reference_id ? payment : await this.#orders(path, "GET"),
      order,
    );
  }
}
