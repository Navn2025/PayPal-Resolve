import type {
  CommerceOrderReceipt, CommerceReport, CommerceSyncInput, CommerceSyncResult, RequestOptions, ResolveClient,
} from "./index.js";

type ContactField = "name" | "email" | "phone";

export interface PostgresReader {
  query(sql: string, values: string[]): Promise<{ rows: Record<string, unknown>[] }>;
}

export interface PostgresCommerceOptions {
  source: string;
  /** Only these columns are queried from the optional contacts view. */
  contactFields?: readonly ContactField[];
}

export interface CommerceBackfillOptions extends RequestOptions {
  /** Resume after the most recent successfully registered order reference. */
  after?: string;
  pageSize?: number;
}

const validOrderReference = (value: unknown): value is string =>
  typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,159}$/.test(value);

interface SyncOptions extends RequestOptions {
  caseId?: string;
}

export class CommerceSourceError extends Error {
  readonly code: "database_error" | "order_not_found" | "unsupported_order";

  constructor(code: CommerceSourceError["code"]) {
    super({
      database_error: "Could not read the app evidence views. Check the database role, views, and timeouts.",
      order_not_found: "The requested order was not found in the app evidence view.",
      unsupported_order: "The order must have a valid revision, at most one payment and no more than 50 line items.",
    }[code]);
    this.name = "CommerceSourceError";
    this.code = code;
  }
}

function scalar<T extends string | number | null | undefined>(value: T): T {
  if (value == null || typeof value === "string" || (typeof value === "number" && Number.isFinite(value))) {
    return value;
  }
  throw new TypeError("Commerce evidence fields must be scalar values.");
}

export function projectCommerceSnapshot(input: CommerceSyncInput, attachCase = true) {
  const payment = input.payment;
  const contact = input.contact;
  return {
    source: scalar(input.source),
    order_reference: scalar(input.order_reference),
    revision: scalar(input.revision),
    ...(attachCase ? { case_id: scalar(input.case_id) } : {}),
    order_status: scalar(input.order_status),
    customer_reference: scalar(input.customer_reference),
    payment: payment && {
      paypal_order_id: scalar(payment.paypal_order_id),
      paypal_capture_id: scalar(payment.paypal_capture_id),
      currency: scalar(payment.currency),
      status: scalar(payment.status),
      captured_amount: scalar(payment.captured_amount),
      refunded_amount: scalar(payment.refunded_amount),
    },
    items: input.items?.map(({ product_id, name, sku, quantity, unit_amount }) => ({
      product_id: scalar(product_id), name: scalar(name), sku: scalar(sku),
      quantity: scalar(quantity), unit_amount: scalar(unit_amount),
    })),
    contact: contact && { name: scalar(contact.name), email: scalar(contact.email), phone: scalar(contact.phone) },
  };
}

/** Connect only an app-owned, read-only role that can select the evidence views. */
export class PostgresCommerce {
  #resolve: ResolveClient;
  #reader: PostgresReader;
  #source: string;
  #sql: string;

  constructor(resolve: ResolveClient, reader: PostgresReader, options: PostgresCommerceOptions) {
    if (!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/.test(options.source)) {
      throw new TypeError("Use a stable source label such as 'my-store'.");
    }
    this.#resolve = resolve;
    this.#reader = reader;
    this.#source = options.source;
    const fields = [...new Set(options.contactFields ?? [])];
    const columns = { name: "c.name", email: "c.email", phone: "c.phone" } as const;
    if (fields.some(field => !Object.hasOwn(columns, field))) {
      throw new TypeError("Choose name, email, and/or phone for contact evidence.");
    }
    const contact = fields.length
      ? ` (SELECT NULLIF(jsonb_strip_nulls(jsonb_build_object(${fields.map(field => "'" + field + "', " + columns[field]).join(", ")})), '{}'::jsonb)
          FROM resolve_evidence.contacts c WHERE c.order_reference = o.order_reference)`
      : "NULL::jsonb";
    // Read one order and its bounded children in one PostgreSQL statement. The
    // caller controls grants; the order ID is a bound parameter, never SQL.
    this.#sql = `
      SELECT o.order_reference, o.revision::text AS revision, o.order_status, o.customer_reference,
        to_jsonb(ARRAY(SELECT jsonb_build_object(
          'paypal_order_id', p.paypal_order_id, 'paypal_capture_id', p.paypal_capture_id,
          'currency', p.currency, 'status', p.status, 'captured_amount', p.captured_amount::text,
          'refunded_amount', p.refunded_amount::text)
          FROM resolve_evidence.payments p WHERE p.order_reference = o.order_reference LIMIT 2)) AS payments,
        to_jsonb(ARRAY(SELECT jsonb_build_object(
          'product_id', i.product_id, 'name', i.name, 'sku', i.sku,
          'quantity', i.quantity, 'unit_amount', i.unit_amount::text)
          FROM resolve_evidence.items i WHERE i.order_reference = o.order_reference
          ORDER BY i.line_id LIMIT 51)) AS items,
        ${contact} AS contact
      FROM resolve_evidence.orders o WHERE o.order_reference = $1 LIMIT 2
    `;
  }

  async #snapshot(orderReference: string, options: SyncOptions): Promise<CommerceSyncInput> {
    if (!validOrderReference(orderReference)) {
      throw new TypeError("Use the app's stable order ID.");
    }
    options.signal?.throwIfAborted();
    let rows: Record<string, unknown>[];
    try {
      ({ rows } = await this.#reader.query(this.#sql, [orderReference]));
    } catch {
      // Driver exceptions can contain SQL values, database URLs or credentials.
      throw new CommerceSourceError("database_error");
    }
    options.signal?.throwIfAborted();
    if (rows.length === 0) throw new CommerceSourceError("order_not_found");
    const row = rows[0];
    const revision = Number(row.revision);
    if (rows.length !== 1 || row.order_reference !== orderReference ||
        !Number.isSafeInteger(revision) || revision < 1 ||
        !Array.isArray(row.payments) || row.payments.length > 1 ||
        !Array.isArray(row.items) || row.items.length > 50) {
      throw new CommerceSourceError("unsupported_order");
    }
    const snapshot = {
      source: this.#source,
      order_reference: orderReference,
      revision,
      case_id: options.caseId,
      order_status: row.order_status,
      customer_reference: row.customer_reference,
      items: row.items,
      payment: row.payments[0],
      contact: row.contact,
    } as CommerceSyncInput;
    return snapshot;
  }

  async sync(orderReference: string, options: SyncOptions = {}): Promise<CommerceSyncResult> {
    return this.#resolve.syncCommerceOrder(await this.#snapshot(orderReference, options), options);
  }

  async register(orderReference: string, options: RequestOptions = {}): Promise<CommerceOrderReceipt> {
    return this.#resolve.registerCommerceOrder(await this.#snapshot(orderReference, options), options);
  }

  /** Publish the rows available to the merchant's reader role in bounded pages. */
  async *registerAll(options: CommerceBackfillOptions = {}): AsyncGenerator<CommerceOrderReceipt> {
    let after = options.after ?? "";
    if (after !== "" && !validOrderReference(after)) throw new TypeError("Use a valid order checkpoint.");
    const size = options.pageSize ?? 50;
    if (!Number.isInteger(size) || size < 1 || size > 100) throw new TypeError("Page size must be between 1 and 100.");
    for (;;) {
      options.signal?.throwIfAborted();
      let rows: Record<string, unknown>[];
      try {
        ({ rows } = await this.#reader.query(
          'SELECT order_reference FROM resolve_evidence.orders WHERE order_reference COLLATE "C" > $1 ORDER BY order_reference COLLATE "C" LIMIT $2::int',
          [after, String(size)],
        ));
      } catch {
        throw new CommerceSourceError("database_error");
      }
      for (const row of rows) {
        if (!validOrderReference(row.order_reference) || row.order_reference <= after) {
          throw new CommerceSourceError("unsupported_order");
        }
        const receipt = await this.register(row.order_reference, options);
        after = row.order_reference;
        yield receipt;
      }
      if (rows.length < size) return;
    }
  }

  /** Sync the selected order, read PayPal, and return the comparison. */
  async inspect(orderReference: string, options: SyncOptions = {}): Promise<CommerceReport> {
    const order = await this.sync(orderReference, options);
    return this.#resolve.refreshCommerceOrder(order.case_id, options);
  }
}
