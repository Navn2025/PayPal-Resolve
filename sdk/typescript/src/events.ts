import type { components } from "./generated.js";

export type ResolutionEventPage = components["schemas"]["EventPage"];
export type ResolutionEvent = components["schemas"]["AppResolutionEvent"];
export interface EventSqlClient {
  query(sql: string, values?: unknown[]): Promise<{ rows: Record<string, unknown>[] }>;
  release(): void;
}
export interface EventSqlPool {
  connect(): Promise<EventSqlClient>;
}
export interface EventApi {
  pullEvents(options?: { afterSequence?: number; limit?: number }, request?: { signal?: AbortSignal }): Promise<ResolutionEventPage>;
}
export type EventHandler = (event: ResolutionEvent, transaction: EventSqlClient) => Promise<void>;

/** Atomically saves app projections and a cursor. Callbacks must use this transaction for their writes. */
export class PostgresResolutionConsumer {
  readonly #database: EventSqlPool;
  readonly #consumer: string;
  readonly #scope: string;
  readonly #merchant: string;
  readonly #source: string;

  constructor(database: EventSqlPool, input: { consumerId: string; merchantId: string; source: string }) {
    if (!/^[A-Za-z0-9_.-]{1,100}$/.test(input.consumerId) || !/^[0-9a-f-]{36}$/i.test(input.merchantId) || !/^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/.test(input.source)) throw new TypeError("Use a stable consumer ID, merchant UUID and app source.");
    this.#database = database; this.#consumer = input.consumerId; this.#merchant = input.merchantId; this.#source = input.source;
    this.#scope = input.merchantId + "/" + input.source;
  }

  /** Explicit opt-in schema setup on the app's writable integration database. */
  async initialize(): Promise<void> {
    const db = await this.#database.connect();
    try {
      await db.query("CREATE TABLE IF NOT EXISTS resolve_sdk_event_cursors (scope TEXT NOT NULL, consumer_id TEXT NOT NULL, last_sequence BIGINT NOT NULL, PRIMARY KEY(scope,consumer_id))");
      await db.query("CREATE TABLE IF NOT EXISTS resolve_sdk_order_projections (scope TEXT NOT NULL, consumer_id TEXT NOT NULL, order_reference TEXT NOT NULL, revision BIGINT NOT NULL, event_id TEXT NOT NULL, snapshot JSONB NOT NULL, PRIMARY KEY(scope,consumer_id,order_reference))");
    } finally { db.release(); }
  }

  async cursor(): Promise<number> {
    const db = await this.#database.connect();
    try {
      const rows = await db.query("SELECT last_sequence FROM resolve_sdk_event_cursors WHERE scope=$1 AND consumer_id=$2", [this.#scope, this.#consumer]);
      const value = Number(rows.rows[0]?.last_sequence ?? 0);
      if (!Number.isSafeInteger(value) || value < 0) throw new Error("Stored Resolve cursor is invalid.");
      return value;
    } finally { db.release(); }
  }

  async apply(page: ResolutionEventPage, onUpdate: EventHandler): Promise<{ applied: number; skipped: number }> {
    if (page.merchant_id !== this.#merchant || page.source !== this.#source || !Array.isArray(page.items) || page.items.length > 100) throw new Error("Resolve event page belongs to another consumer scope.");
    const events = page.items.map(event => structuredClone(event)).sort((a,b) => a.sequence-b.sequence);
    for (const event of events) {
      if (event.type !== "resolution.updated" || !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(event.id) || event.source !== this.#source || !Number.isSafeInteger(event.sequence) || event.sequence < 1 || !Number.isSafeInteger(event.revision) || event.revision < 1 || typeof event.order_reference !== "string" || typeof event.snapshot !== "object" || !event.snapshot) throw new Error("Invalid Resolve state event.");
    }
    const db = await this.#database.connect();
    let applied=0, skipped=0;
    try {
      await db.query("BEGIN");
      await db.query("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", [this.#scope + "/" + this.#consumer]);
      await db.query("INSERT INTO resolve_sdk_event_cursors VALUES ($1,$2,0) ON CONFLICT DO NOTHING", [this.#scope,this.#consumer]);
      const saved = await db.query("SELECT last_sequence FROM resolve_sdk_event_cursors WHERE scope=$1 AND consumer_id=$2 FOR UPDATE", [this.#scope,this.#consumer]);
      let cursor = Number(saved.rows[0]!.last_sequence);
      for (const event of events) {
        if (event.sequence <= cursor) { skipped++; continue; }
        const prior = await db.query("SELECT revision,snapshot=$4::jsonb AS same FROM resolve_sdk_order_projections WHERE scope=$1 AND consumer_id=$2 AND order_reference=$3", [this.#scope,this.#consumer,event.order_reference,JSON.stringify(event.snapshot)]);
        const revision = Number(prior.rows[0]?.revision ?? 0);
        if (event.revision === revision && !prior.rows[0]?.same) throw new Error("Resolve event revision conflicts with the stored snapshot.");
        if (event.revision > revision) {
          await onUpdate(structuredClone(event), db);
          await db.query("INSERT INTO resolve_sdk_order_projections VALUES ($1,$2,$3,$4,$5,$6::jsonb) ON CONFLICT(scope,consumer_id,order_reference) DO UPDATE SET revision=excluded.revision,event_id=excluded.event_id,snapshot=excluded.snapshot", [this.#scope,this.#consumer,event.order_reference,event.revision,event.id,JSON.stringify(event.snapshot)]);
          applied++;
        } else skipped++;
        cursor=event.sequence;
      }
      await db.query("UPDATE resolve_sdk_event_cursors SET last_sequence=$3 WHERE scope=$1 AND consumer_id=$2", [this.#scope,this.#consumer,cursor]);
      await db.query("COMMIT");
      return { applied, skipped };
    } catch (error) { await db.query("ROLLBACK"); throw error; }
    finally { db.release(); }
  }

  async poll(api: EventApi, onUpdate: EventHandler, options: { maxPages?: number; signal?: AbortSignal } = {}): Promise<{ applied: number; skipped: number; cursor: number }> {
    const maxPages = options.maxPages ?? 5;
    if (!Number.isInteger(maxPages) || maxPages<1 || maxPages>100) throw new TypeError("Use maxPages between 1 and 100.");
    let applied=0, skipped=0;
    for(let i=0;i<maxPages;i++) {
      const page=await api.pullEvents({ afterSequence: await this.cursor(), limit:100 }, options.signal ? {signal:options.signal} : {});
      const result=await this.apply(page,onUpdate); applied+=result.applied; skipped+=result.skipped;
      if(!page.has_more) break;
    }
    return { applied, skipped, cursor:await this.cursor() };
  }
}
