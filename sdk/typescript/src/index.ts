import type { paths } from "./generated.js";

type Auth = paths["/auth/me"]["get"];
type Cases = paths["/resolution-cases"];
type Case = paths["/resolution-cases/{case_id}"]["get"];
type Link = paths["/resolution-cases/{case_id}/customer-link"];
type Timeline = paths["/resolution-cases/{case_id}/timeline"]["get"];
type Upsert = paths["/resolution-cases/upsert"]["post"];
type RecordLink = paths["/resolution-cases/{case_id}/evidence/records"]["post"];
type EvidenceEvent = paths["/resolution-cases/{case_id}/evidence/events"]["post"];
type Refresh = paths["/resolution-cases/{case_id}/evidence/refresh"]["post"];
type Bundle = paths["/resolution-cases/{case_id}/evidence-bundle"]["get"];

export type Merchant = Auth["responses"][200]["content"]["application/json"];
export type CreateCaseInput = Cases["post"]["requestBody"]["content"]["application/json"];
export type ResolutionCase = Case["responses"][200]["content"]["application/json"];
export type CasePage = Cases["get"]["responses"][200]["content"]["application/json"];
export type Pagination = NonNullable<Cases["get"]["parameters"]["query"]>;
export type CaseTimeline = Timeline["responses"][200]["content"]["application/json"];
export type TimelineOptions = NonNullable<Timeline["parameters"]["query"]>;
export type UpsertCaseInput = Upsert["requestBody"]["content"]["application/json"];
export type LinkRecordInput = RecordLink["requestBody"]["content"]["application/json"];
export type LinkedRecord = RecordLink["responses"][200]["content"]["application/json"];
export type AddEvidenceInput = EvidenceEvent["requestBody"]["content"]["application/json"];
export type EvidenceReceipt = EvidenceEvent["responses"][200]["content"]["application/json"];
export type EvidenceRefresh = Refresh["responses"][200]["content"]["application/json"];
export type EvidenceBundle = Bundle["responses"][200]["content"]["application/json"];
export type EvidenceSummary = NonNullable<ResolutionCase["evidence_summary"]>;
export type CustomerLinkInput = Link["post"]["requestBody"]["content"]["application/json"];
export type IssuedCustomerLink = Link["post"]["responses"][201]["content"]["application/json"];
export type CustomerLinkStatus = Link["get"]["responses"][200]["content"]["application/json"];

export interface ResolveClientOptions {
  /** Resolve's FastAPI base URL. Keep this in trusted server configuration. */
  baseUrl: string;
  /** Merchant key issued by Resolve. Keep this in a server-side secret. */
  apiKey: string;
  /** Overall request timeout in milliseconds. Defaults to 10,000. */
  timeoutMs?: number;
}

export interface RequestOptions {
  signal?: AbortSignal;
}

export class ResolveApiError extends Error {
  readonly status: number;
  readonly code: "case_reference_conflict" | "record_conflict" | "evidence_event_conflict" | "refresh_conflict" | undefined;

  constructor(status: number, code?: ResolveApiError["code"]) {
    const messages: Record<number, string> = {
      401: "Resolve did not accept the merchant access key.",
      403: "The merchant is not allowed to perform this action.",
      404: "Resolve did not find this resource in the merchant workspace.",
      409: "The request conflicts with the current Resolve state.",
      422: "Resolve rejected the request fields.",
      429: "Resolve is rate limiting this request.",
    };
    const conflict = {
      case_reference_conflict: "The external reference is already used with different case data.",
      record_conflict: "The record conflicts with the linked payment or source, or the case reached its link limit.",
      evidence_event_conflict: "The source event ID is already used with different evidence.",
      refresh_conflict: "The linked records changed during refresh. Try again.",
    };
    super(code ? conflict[code] : messages[status] ?? `Resolve returned HTTP ${status}.`);
    this.name = "ResolveApiError";
    this.status = status;
    this.code = code;
  }
}

export class ResolveTransportError extends Error {
  readonly code: "network" | "timeout" | "aborted" | "invalid_response";

  constructor(code: ResolveTransportError["code"]) {
    super({
      network: "Could not reach the Resolve API.",
      timeout: "The Resolve request timed out.",
      aborted: "The Resolve request was cancelled.",
      invalid_response: "The Resolve API did not return a JSON object.",
    }[code]);
    this.name = "ResolveTransportError";
    this.code = code;
  }
}

function apiBase(value: string): string {
  const loopback = ["127.0.0.1", "localhost", "[::1]"];
  let parsed: URL;
  try { parsed = new URL(value); } catch { throw new TypeError("Set an absolute Resolve API base URL."); }
  if ((parsed.protocol !== "https:" &&
      !(parsed.protocol === "http:" && loopback.includes(parsed.hostname))) ||
      parsed.username || parsed.password || parsed.search || parsed.hash) {
    throw new TypeError("Use an HTTPS Resolve API base URL, or HTTP on loopback for development.");
  }
  return parsed.origin + parsed.pathname.replace(/\/+$/, "");
}

function casePath(caseId: string): string {
  if (typeof caseId !== "string" || !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(caseId)) {
    throw new TypeError("Use the Resolve case UUID.");
  }
  return "/resolution-cases/" + caseId;
}

function query(page: TimelineOptions): string {
  const params = new URLSearchParams();
  if (page.limit !== undefined) params.set("limit", String(page.limit));
  if (page.offset !== undefined) params.set("offset", String(page.offset));
  if (page.before_sequence !== undefined && page.before_sequence !== null) {
    params.set("before_sequence", String(page.before_sequence));
  }
  return params.size ? "?" + params.toString() : "";
}

/** Server-side client for an existing merchant's Resolve workspace. */
export class ResolveClient {
  #base: string;
  #apiKey: string;
  #timeoutMs: number;

  constructor(options: ResolveClientOptions) {
    if (typeof window !== "undefined" && typeof window.document !== "undefined") {
      throw new TypeError("Use ResolveClient on the server; never put a merchant key in browser code.");
    }
    if (typeof options.apiKey !== "string" || !/^rslv_[A-Za-z0-9_-]{43}$/.test(options.apiKey)) {
      throw new TypeError("Set a valid Resolve merchant access key.");
    }
    this.#base = apiBase(options.baseUrl);
    this.#apiKey = options.apiKey;
    this.#timeoutMs = options.timeoutMs ?? 10_000;
    if (!Number.isInteger(this.#timeoutMs) || this.#timeoutMs < 1 || this.#timeoutMs > 120_000) {
      throw new TypeError("Set timeoutMs to an integer between 1 and 120,000.");
    }
  }

  getMerchant(options?: RequestOptions): Promise<Merchant> {
    return this.#request("GET", "/auth/me", options);
  }

  createCase(input: CreateCaseInput, options?: RequestOptions): Promise<ResolutionCase> {
    return this.#request("POST", "/resolution-cases", options, input);
  }

  upsertCase(input: UpsertCaseInput, options?: RequestOptions): Promise<ResolutionCase> {
    return this.#request("POST", "/resolution-cases/upsert", options, input);
  }

  linkRecord(caseId: string, input: LinkRecordInput, options?: RequestOptions): Promise<LinkedRecord> {
    return this.#request("POST", casePath(caseId) + "/evidence/records", options, input);
  }

  addEvidence(caseId: string, input: AddEvidenceInput, options?: RequestOptions): Promise<EvidenceReceipt> {
    return this.#request("POST", casePath(caseId) + "/evidence/events", options, input);
  }

  refreshEvidence(caseId: string, options?: RequestOptions): Promise<EvidenceRefresh> {
    return this.#request("POST", casePath(caseId) + "/evidence/refresh", options);
  }

  getCase(caseId: string, options?: RequestOptions): Promise<ResolutionCase> {
    return this.#request("GET", casePath(caseId), options);
  }

  listCases(page: Pagination = {}, options?: RequestOptions): Promise<CasePage> {
    return this.#request("GET", "/resolution-cases" + query(page), options);
  }

  getCaseTimeline(caseId: string, page: Pagination = {}, options?: RequestOptions): Promise<CaseTimeline> {
    return this.#request("GET", casePath(caseId) + "/timeline" + query(page), options);
  }

  getTimeline(caseId: string, page: TimelineOptions = {}, options?: RequestOptions): Promise<CaseTimeline> {
    return this.#request("GET", casePath(caseId) + "/timeline" + query(page), options);
  }

  getEvidenceBundle(caseId: string, page: Pagination = {}, options?: RequestOptions): Promise<EvidenceBundle> {
    return this.#request("GET", casePath(caseId) + "/evidence-bundle" + query(page), options);
  }

  /** Replaces any previous link. Share only with the intended customer. */
  issueCustomerLink(caseId: string, input: CustomerLinkInput = {}, options?: RequestOptions): Promise<IssuedCustomerLink> {
    return this.#request("POST", casePath(caseId) + "/customer-link", options, input);
  }

  /** Alias for issueCustomerLink: replaces any previous buyer link. */
  createBuyerLink(caseId: string, input: CustomerLinkInput = {}, options?: RequestOptions): Promise<IssuedCustomerLink> {
    return this.issueCustomerLink(caseId, input, options);
  }

  getCustomerLink(caseId: string, options?: RequestOptions): Promise<CustomerLinkStatus> {
    return this.#request("GET", casePath(caseId) + "/customer-link", options);
  }

  revokeCustomerLink(caseId: string, options?: RequestOptions): Promise<CustomerLinkStatus> {
    return this.#request("DELETE", casePath(caseId) + "/customer-link", options);
  }

  async #request<T>(
    method: "GET" | "POST" | "DELETE",
    path: string,
    options?: RequestOptions,
    input?: CreateCaseInput | CustomerLinkInput | UpsertCaseInput | LinkRecordInput | AddEvidenceInput,
  ): Promise<T> {
    const body = input === undefined ? undefined : JSON.stringify(input);
    const deadline = AbortSignal.timeout(this.#timeoutMs);
    const signal = options?.signal ? AbortSignal.any([options.signal, deadline]) : deadline;
    const headers: Record<string, string> = {
      Accept: "application/json",
      Authorization: "Bearer " + this.#apiKey,
    };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    let response: Response;
    try {
      response = await fetch(this.#base + path, {
        method, headers, ...(body === undefined ? {} : { body }),
        signal, redirect: "manual", credentials: "omit", cache: "no-store",
      });
    } catch {
      throw new ResolveTransportError(signal.aborted ? (signal.reason === deadline.reason ? "timeout" : "aborted") : "network");
    }
    if (!response.ok) {
      // Don't attach a validation payload: it can include the caller's private input.
      void response.body?.cancel().catch(() => {});
      const conflict = response.status !== 409 ? undefined
        : path.endsWith("/upsert") ? "case_reference_conflict"
        : path.endsWith("/evidence/records") ? "record_conflict"
        : path.endsWith("/evidence/events") ? "evidence_event_conflict"
        : path.endsWith("/evidence/refresh") ? "refresh_conflict" : undefined;
      throw new ResolveApiError(response.status, conflict);
    }
    let value: unknown;
    try { value = await response.json(); } catch {
      throw new ResolveTransportError(signal.aborted ? (signal.reason === deadline.reason ? "timeout" : "aborted") : "invalid_response");
    }
    if (typeof value !== "object" || value === null || Array.isArray(value)) {
      throw new ResolveTransportError("invalid_response");
    }
    return value as T;
  }
}
