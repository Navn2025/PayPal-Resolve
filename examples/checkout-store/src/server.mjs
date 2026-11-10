import { createHash, randomBytes, randomUUID } from "node:crypto";
import { readFileSync, mkdirSync } from "node:fs";
import { createServer } from "node:http";
import { dirname, resolve as localPath } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { ResolveClient } from "@resolve-paypal/sdk";
import { catalog, money, quote, ShopError } from "./catalog.mjs";
import { SandboxPayPal } from "./paypal.mjs";

const GUID = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/;
const assets = new Map([
  ["/", ["index.html", "text/html"]],
  ["/app.js", ["app.js", "text/javascript"]],
  ["/styles.css", ["styles.css", "text/css"]],
  ["/products.svg", ["products.svg", "image/svg+xml"]],
].map(([route, [name, media]]) => [route, [readFileSync(new URL("../public/" + name, import.meta.url)), media]]));

function createShop(env) {
  const port = Number(env.SHOP_PORT ?? "4173");
  if (!Number.isInteger(port) || port < 0 || port > 65535) throw new Error("Set a valid SHOP_PORT.");
  const path = env.SHOP_DATABASE_PATH === ":memory:" ? ":memory:" : localPath(env.SHOP_DATABASE_PATH || "data/store.sqlite3");
  if (path !== ":memory:") mkdirSync(dirname(path), { recursive: true });
  const db = new DatabaseSync(path);
  db.exec(`
    PRAGMA busy_timeout=5000;
    CREATE TABLE IF NOT EXISTS store_orders (
      id TEXT PRIMARY KEY, session_hash TEXT NOT NULL, checkout_key TEXT NOT NULL,
      lines TEXT NOT NULL, total INTEGER NOT NULL, created_at INTEGER NOT NULL,
      create_key TEXT NOT NULL, capture_key TEXT NOT NULL,
      paypal_order TEXT, approval TEXT, capture_id TEXT, payment_state TEXT,
      case_id TEXT, verification TEXT, sync_error INTEGER NOT NULL DEFAULT 0,
      UNIQUE (session_hash, checkout_key)
    )
  `);
  const paypal = env.SHOP_PAYPAL_CLIENT_ID && env.SHOP_PAYPAL_CLIENT_SECRET && env.SHOP_PAYPAL_MERCHANT_ID
    ? new SandboxPayPal(env.SHOP_PAYPAL_CLIENT_ID, env.SHOP_PAYPAL_CLIENT_SECRET, env.SHOP_PAYPAL_MERCHANT_ID) : null;
  const evidence = env.RESOLVE_API_URL && env.RESOLVE_API_KEY
    ? new ResolveClient({ baseUrl: env.RESOLVE_API_URL, apiKey: env.RESOLVE_API_KEY, timeoutMs: 25_000, source: "field-brew-store" }) : null;
  const enabled = Boolean(paypal && evidence);
  const find = db.prepare("SELECT * FROM store_orders WHERE id=? AND session_hash=?");
  const byRequest = db.prepare("SELECT * FROM store_orders WHERE session_hash=? AND checkout_key=?");
  const insert = db.prepare(`
    INSERT INTO store_orders (id,session_hash,checkout_key,lines,total,created_at,create_key,capture_key)
    VALUES (?,?,?,?,?,?,?,?)
  `);
  const savePayPal = db.prepare("UPDATE store_orders SET paypal_order=?, approval=? WHERE id=?");
  const savePayment = db.prepare("UPDATE store_orders SET capture_id=?, payment_state=? WHERE id=?");
  const saveCase = db.prepare("UPDATE store_orders SET case_id=? WHERE id=?");
  const saveEvidence = db.prepare("UPDATE store_orders SET verification=?, sync_error=? WHERE id=?");
  const work = new Map();
  let origin;

  function get(id, session) {
    const row = find.get(id, session);
    if (!row) throw new ShopError(404, "That receipt is not available in this browser.");
    return row;
  }

  async function serial(key, task) {
    if (work.has(key)) return work.get(key);
    const pending = Promise.resolve().then(task);
    work.set(key, pending);
    try { return await pending; }
    finally { work.delete(key); }
  }

  function receipt(row) {
    return {
      id: row.id,
      reference: "FIELD-" + row.id,
      total: money(row.total),
      lines: JSON.parse(row.lines),
      state: row.payment_state ?? "awaiting_approval",
      caseId: row.case_id ?? null,
      comparison: row.verification ? JSON.parse(row.verification) : null,
      resolveUnavailable: Boolean(row.sync_error),
    };
  }

  async function sync(row) {
    try {
      if (!evidence) throw new Error();
      const result = await evidence.syncCommerceOrder({
        source: "field-brew-store",
        order_reference: "FIELD-" + row.id,
        revision: 1,
        order_status: "paid",
        payment: {
          paypal_order_id: row.paypal_order,
          paypal_capture_id: row.capture_id,
          currency: "USD",
          status: "completed",
          captured_amount: money(row.total),
          refunded_amount: "0.00",
        },
        items: JSON.parse(row.lines).map(line => ({
          product_id: line.id, name: line.name, quantity: line.quantity, unit_amount: money(line.cents),
        })),
      });
      saveCase.run(result.case_id, row.id);
      const proof = await evidence.refreshCommerceOrder(result.case_id);
      saveEvidence.run(JSON.stringify({
        status: proof.status,
        checkedAt: proof.last_checked_at,
        checks: proof.checks.map(({ field, status, app_value, paypal_value }) => ({
          field, status,
          // Store only the values useful on a buyer's demo receipt.
          ...(["captured_amount", "refunded_amount", "payment_status"].includes(field)
            ? { app: app_value, paypal: paypal_value } : {}),
        })),
      }), 0, row.id);
    } catch {
      // A Resolve outage must not turn a captured payment into a failed sale.
      // Leave any earlier check visible alongside the explicit retry state.
      saveEvidence.run(row.verification, 1, row.id);
    }
  }

  function session(req, res, create = false) {
    let token = (req.headers.cookie ?? "").match(/(?:^|;\s*)field_brew=([a-f0-9]{64})(?:;|$)/)?.[1];
    if (!token && create) {
      token = randomBytes(32).toString("hex");
      res.setHeader("Set-Cookie", "field_brew=" + token + "; Path=/; HttpOnly; SameSite=Lax; Max-Age=86400");
    }
    return token ? createHash("sha256").update(token).digest("hex") : null;
  }

  async function body(req) {
    if (!req.headers["content-type"]?.startsWith("application/json")) throw new ShopError(415, "Send a JSON request.");
    let size = 0;
    const chunks = [];
    // Read the bounded payload before creating any order or making a provider call.
    for await (const chunk of req) {
      size += chunk.length;
      if (size > 8192) throw new ShopError(413, "This request is too large.");
      chunks.push(chunk);
    }
    try {
      const value = JSON.parse(Buffer.concat(chunks).toString("utf8"));
      if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error();
      return value;
    } catch {
      throw new ShopError(400, "Send a valid checkout request.");
    }
  }

  function json(res, status, value) {
    res.writeHead(status, { "Content-Type": "application/json; charset=utf-8" });
    res.end(JSON.stringify(value));
  }

  const server = createServer(async (req, res) => {
    res.setHeader("Cache-Control", "no-store");
    res.setHeader("Referrer-Policy", "no-referrer");
    res.setHeader("X-Content-Type-Options", "nosniff");
    res.setHeader("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'");
    try {
      if (req.headers.host !== new URL(origin).host) throw new ShopError(403, "Open the printed local store URL.");
      const url = new URL(req.url, origin);
      if (url.origin !== origin) throw new ShopError(403, "Invalid request origin.");
      const route = url.pathname;
      if (req.method === "GET" && assets.has(route)) {
        if (route === "/") session(req, res, true);
        const [file, media] = assets.get(route);
        res.writeHead(200, { "Content-Type": media + "; charset=utf-8" });
        res.end(file);
        return;
      }
      if (req.method === "GET" && route === "/api/catalog") {
        session(req, res, true);
        return json(res, 200, { catalog, checkoutEnabled: enabled });
      }
      const sid = session(req, res);
      if (!sid) throw new ShopError(404, "Open the store to start checkout.");
      if (req.method === "POST" && req.headers.origin && req.headers.origin !== origin) {
        throw new ShopError(403, "Only this storefront may submit a checkout.");
      }
      if (req.method === "POST" && route === "/api/orders") {
        if (!enabled) throw new ShopError(503, "Connect the PayPal Sandbox and Resolve settings to enable checkout.");
        const input = await body(req);
        if (typeof input.requestId !== "string" || !GUID.test(input.requestId)) {
          throw new ShopError(400, "Use a valid checkout request ID.");
        }
        const { lines, total } = quote(input.items);
        const encoded = JSON.stringify(lines);
        let row = byRequest.get(sid, input.requestId);
        if (!row) {
          const id = randomUUID();
          insert.run(id, sid, input.requestId, encoded, total, Date.now(), randomUUID(), randomUUID());
          row = get(id, sid);
        } else if (row.lines !== encoded) {
          throw new ShopError(409, "The cart changed. Start a new checkout for the updated items.");
        }
        const started = await serial("create:" + row.id, async () => {
          if (Date.now() - row.created_at > 30 * 60 * 1000) {
            throw new ShopError(409, "This checkout has expired. Start a new checkout.");
          }
          if (!row.paypal_order) {
            const created = await paypal.create(row, origin);
            savePayPal.run(created.id, created.approval, row.id);
          }
          return get(row.id, sid);
        });
        return json(res, 200, { ...receipt(started), approvalUrl: started.approval });
      }
      const match = route.match(/^\/api\/orders\/([a-f0-9-]+)(?:\/(capture|verify|support|resolution|support-link|refund-journey|context|return-eligibility))?$/);
      if (!match || !GUID.test(match[1])) throw new ShopError(404, "That page does not exist.");
      const [, id, action] = match;
      if (req.method === "GET" && !action) return json(res, 200, receipt(get(id, sid)));
      if (["support", "resolution", "support-link", "refund-journey", "context", "return-eligibility"].includes(action)) {
        if (req.method !== "POST") throw new ShopError(405, "Use the order support action.");
        const order = get(id, sid); // Validate this browser owns the order before contacting Resolve.
        if (!evidence || order.payment_state !== "completed" || !order.case_id) throw new ShopError(409, "Support is available after the paid order is synced.");
        const input = await body(req);
        try {
          const reference = "FIELD-" + order.id;
          const result = action === "refund-journey" ? await evidence.getRefundJourney(reference)
            : action === "context" ? await evidence.getSupportContext(reference)
            : action === "return-eligibility" ? await evidence.getReturnEligibility(reference,{items:JSON.parse(order.lines).map(line=>({product_id:line.id,quantity:line.quantity}))})
            : action === "resolution" ? await evidence.getOrderResolution(reference)
            : action === "support-link" ? await evidence.createSupportLink(reference)
            : await evidence.openIssue({ orderId: reference, requestId: input.requestId, reason: input.reason, message: input.message, requestedResolution: input.requestedResolution });
          return json(res, action === "resolution" ? 200 : 201, result);
        } catch (error) {
          const status = Number.isInteger(error.status) && error.status >= 400 && error.status <= 499 ? error.status : 503;
          throw new ShopError(status, status === 403 ? "Enable a support integration key for field-brew-store." : status === 409 ? "This request changed. Review the saved issue before retrying." : "Order support is unavailable. Try again shortly.");
        }
      }
      if (req.method !== "POST" || !action) throw new ShopError(404, "That page does not exist.");
      if (!enabled) throw new ShopError(503, "Checkout settings are not available.");
      const input = await body(req);
      const owner = get(id, sid);
      if (action === "capture" && (typeof input.token !== "string" || input.token !== owner.paypal_order)) {
        throw new ShopError(409, "The PayPal approval does not match this order.");
      }
      const result = await serial("payment:" + id, async () => {
        let row = get(id, sid);
        if (action === "capture") {
          if (row.payment_state !== "completed") {
            const payment = await paypal.capture(row);
            if (row.capture_id && row.capture_id !== payment.id) {
              throw new ShopError(502, "The PayPal capture reference changed. Review this order.");
            }
            savePayment.run(payment.id, payment.state, id);
            row = get(id, sid);
          }
        }
        if (row.payment_state === "completed" && (action === "verify" || !row.verification || row.sync_error)) {
          await sync(row);
        } else if (action === "verify") {
          throw new ShopError(409, "PayPal has not completed this payment yet.");
        }
        return receipt(get(id, sid));
      });
      return json(res, 200, result);
    } catch (error) {
      if (!res.headersSent && !res.destroyed) {
        json(res, error instanceof ShopError ? error.status : 500, {
          message: error instanceof ShopError ? error.message : "The store could not complete that request. Please try again.",
        });
      }
    }
  });

  server.on("close", () => db.close());
  server.listen(port, "127.0.0.1", () => {
    origin = "http://127.0.0.1:" + server.address().port;
    console.log("Field Brew Supply: " + origin);
    console.log(enabled ? "Sandbox checkout enabled." : "Catalog preview. Configure Sandbox and Resolve to enable checkout.");
  });
}

createShop(process.env);
