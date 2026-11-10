"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Activity, ArrowRight, BookOpen, CheckCircle2, ChevronRight, CircleAlert, ClipboardList, FlaskConical, Inbox, Layers3, Link2, LogOut, Package, Plus, RefreshCw, Search, Settings2, ShieldCheck, X } from "lucide-react";
import Link from "next/link";
import { DemoStore, demoPrimary } from "@/lib/demo";
import { activeApproval, amountCents, ApiError, dateText, money, outcomeLabels, pretty, reconcileLabels, shortId, timeText, uuid,
  type Approval, type CaseView, type Execution, type LegacyCase, type Merchant, type Outcome, type Page,
  type PromiseView, type Reconciliation, type Requester, type Review, type Session, type Terms, type Timeline } from "@/lib/domain";
import { backendRequest, readJson } from "@/lib/http";
import { workflowLabels, type Operations, type Workflow } from "@/lib/customer";
import { Badge, Brand, Button, Empty, Notice, remedyIcons } from "./ui";
import { CaseDesk, type DeskTab } from "./case-desk";
import { InvestigationReviewPanel } from "./investigation-review";
import { PromiseExtractionPanel } from "./promise-extraction";
import { PromiseHealthPanel } from "./promise-health";
import { CaseForm, ConnectForm, EvidenceForm, LocalGuide, PromiseForm, RefundForm, ReviewForm, type PromiseDraft } from "./forms";
import { InviteForm, OperationsForm, PaymentLinkForm } from "./merchant-triage";

const CASE_PAGE = 12, EVENT_PAGE = 30;
type Filter = "all" | Outcome | Workflow | "unread";
type Nav = "inbox" | "review";
type Dialog = { kind: "connect" | "case" | "guide" | "invite" } | { kind: "payment-link"; item: CaseView } | { kind: "operations"; id: string; fields: Operations } | { kind: "promise"; edit?: PromiseView; draft?: PromiseDraft }
  | { kind: "evidence"; promise: PromiseView } | { kind: "approve"; basis: Reconciliation; prefill?: string }
  | { kind: "execute"; approval: Approval } | { kind: "review"; item: Review };
type Detail = {
  item: CaseView; timeline: Timeline | null; timelineError?: string; payment: LegacyCase | null;
  basis: Reconciliation | null; approvals: Approval[]; executions: Execution[]; paymentError?: string;
};
const initialPage = (items: CaseView[]): Page<CaseView> => ({ items, total: items.length, limit: CASE_PAGE, offset: 0 });
const errorText = (error: unknown) => error instanceof Error ? error.message : "Something went wrong. Try again.";

function StatusMetrics({ cases, total }: { cases: CaseView[]; total: number }) {
  const stats = [
    { label: "Open cases", value: cases.filter((c) => c.outcome !== "fulfilled").length, Icon: Layers3, tone: "blue" },
    { label: "Needs review", value: cases.filter((c) => c.outcome === "needs_review").length, Icon: CircleAlert, tone: "amber" },
    { label: "Pending verification", value: cases.filter((c) => c.outcome === "pending").length, Icon: Activity, tone: "purple" },
    { label: "Fulfilled", value: cases.filter((c) => c.outcome === "fulfilled").length, Icon: CheckCircle2, tone: "green" },
  ];
  return <div className="metrics-wrap" aria-label={cases.length < total ? "Metrics for loaded cases" : "Case metrics"}>
    <div className="metrics-grid">{stats.map(({ label, value, Icon, tone }) => (
      <div className="status-metric" key={label}><span className={`metric-icon metric-${tone}`}><Icon size={18} /></span>
        <div><span>{label}</span><strong>{value.toString().padStart(2, "0")}</strong></div></div>))}</div>
    {cases.length < total && <p className="metric-scope">Counts cover {cases.length} of {total} cases.</p>}
  </div>;
}

function InboxPane({ cases, selected, select, filter, setFilter, search, setSearch, more, onMore, loading, onNew, demo }: {
  cases: CaseView[]; selected: string | null; select: (id: string) => void; filter: Filter; setFilter: (filter: Filter) => void;
  search: string; setSearch: (search: string) => void; more: boolean; onMore: () => void; loading: boolean; onNew: () => void;
  demo: boolean;
}) {
  const needle = search.trim().toLowerCase();
  const items = cases.filter((item) => (filter === "all" || item.outcome === filter || item.operations?.workflow === filter ||
    (filter === "unread" && !!item.operations?.unread_count)) &&
    (!demo || !needle || [item.title, item.order_reference ?? "", item.id, item.operations?.assignee ?? ""].some((value) => value.toLowerCase().includes(needle))));
  return <aside className="inbox-pane" aria-label="Case inbox">
    <div className="inbox-head"><div><div className="eyebrow">WORK QUEUE</div><h2>Case inbox</h2></div><span className="inbox-count">{cases.length}</span></div>
    <label className="search-box"><Search size={17} /><input aria-label="Search cases" placeholder="Search cases…" maxLength={160} value={search} onChange={(event) => setSearch(event.target.value)} />
      {search && <Button variant="ghost" className="icon-button" aria-label="Clear search" onClick={() => setSearch("")}><X size={15} /></Button>}</label>
    <div className="filters" aria-label="Filter cases">
      {([["all", "All"], ["waiting", "Action"], ["needs_review", "Review"], ["pending", "Pending"], ["fulfilled", "Done"]] as const).map(([id, label]) =>
        <button type="button" key={id} className={filter === id ? "active" : ""} aria-pressed={filter === id} onClick={() => setFilter(id)}>{label}</button>)}
    </div>
    <div className="filters inbox-flow-filters" aria-label="Filter by next step">
      {([["waiting_on_customer", "Waiting on customer"], ["needs_approval", "Needs approval"], ["pending_with_paypal", "Pending with PayPal"], ["unread", "Unread"]] as const).map(([id, label]) =>
        <button type="button" key={id} className={filter === id ? "active" : ""} aria-pressed={filter === id} onClick={() => setFilter(id)}>{label}</button>)}
    </div>
    <div className="case-list">
      {items.map((item) => {
        const kind = item.promises.find((p) => p.terms.target.kind === "refund")?.terms.target.kind ?? item.promises[0]?.terms.target.kind;
        const Icon = kind ? remedyIcons[kind] : ClipboardList;
        const ops = item.operations;
        const due = ops?.due_at ?? ops?.promise_due_at;
        return <button type="button" key={item.id} className={`case-row ${selected === item.id ? "selected" : ""}`}
          aria-current={selected === item.id ? "true" : undefined} onClick={() => select(item.id)}>
          <span className={`case-row-icon case-tone-${item.outcome}`}><Icon size={17} /></span>
          <span className="case-row-body"><span className="case-row-meta"><span>{item.order_reference || "Case " + shortId(item.id)}</span><time dateTime={item.created_at}>{dateText(item.created_at)}</time></span>
            <strong>{item.title}</strong><span className="case-row-badges"><Badge outcome={item.outcome} />
              {!!ops?.unread_count && <span className="unread-chip">{ops.unread_count} unread</span>}</span>
            {ops && <span className="case-row-triage"><span>{workflowLabels[ops.workflow]}{ops.assignee ? " · " + ops.assignee : ""}</span>
              {due && ops.workflow !== "resolved" && <span className={ops.overdue ? "overdue" : ""}>{ops.overdue ? "Overdue" : "Due " + dateText(due)}</span>}</span>}
          </span><ChevronRight className="case-arrow" size={16} />
        </button>;
      })}
      {!items.length && <Empty title={loading ? "Loading cases…" : cases.length ? "No matching cases" : "No cases yet"}
        detail={loading ? "Reading the merchant workspace." : cases.length ? "Try a different filter or search." : "Start by recording a customer issue."}
        action={!loading && !cases.length ? <Button className="small-button" onClick={onNew}><Plus size={15} /> New case</Button> : undefined} />}
    </div>
    {more && <Button className="load-cases" onClick={onMore} disabled={loading}>{loading ? "Loading…" : "Load more cases"}</Button>}
  </aside>;
}

function ReviewPane({ items, total, status, setStatus, loading, error, onMore, cases, onOpen, onResolve }: {
  items: Review[]; total: number; status: "open" | "resolved"; setStatus: (status: "open" | "resolved") => void; loading: boolean;
  error: string; onMore: () => void; cases: CaseView[]; onOpen: (id: string) => void; onResolve: (item: Review) => void;
}) {
  return <section className="review-pane section-card">
    <div className="section-head"><div><div className="eyebrow">EXCEPTIONS</div><h2>Review queue</h2></div>
      <div className="filters" aria-label="Review status">{(["open", "resolved"] as const).map((state) => <button type="button" key={state}
        className={status === state ? "active" : ""} aria-pressed={status === state} onClick={() => setStatus(state)}>{pretty(state)}</button>)}</div></div>
    {error && <Notice>{error}</Notice>}
    {!items.length && <Empty title={loading ? "Loading review items…" : "Nothing to review"} detail={loading ? "Reading exceptions." : "Items appear here when a provider or refund needs attention."} />}
    <div className="review-list">{items.map((item) => {
      const linked = cases.find((entry) => entry.refund_case_id === item.case_id);
      return <article className="review-row" key={item.id}><span className="metric-icon metric-amber"><CircleAlert size={20} /></span>
        <div><strong>{pretty(item.reason)}</strong><p>{linked?.title ?? item.capture_id ?? "Provider exception"} · {timeText(item.updated_at)}</p>
          {item.blocking && <span className="muted">Needs new provider evidence before it can be resolved.</span>}</div>
        <div className="review-actions">{linked && <Button onClick={() => onOpen(linked.id)} className="small-button">Open case <ArrowRight size={14} /></Button>}
          {item.status === "open" && !item.blocking && <Button className="small-button" onClick={() => onResolve(item)}>Resolve item</Button>}</div>
      </article>;
    })}</div>
    {items.length < total && <Button onClick={onMore} disabled={loading}>{loading ? "Loading…" : "Load more review items"}</Button>}
  </section>;
}

async function fetchSummary(request: Requester, id: string): Promise<CaseView> {
  const url = "/resolution-cases/" + id;
  const [item, operations] = await Promise.all([request<CaseView>(url), request<Operations>(url + "/operations")]);
  return { ...item, operations };
}

async function fetchCase(request: Requester, id: string): Promise<Detail> {
  const root = "/resolution-cases/" + id;
  const [item, log] = await Promise.all([
    fetchSummary(request, id),
    request<Timeline>(root + `/timeline?limit=${EVENT_PAGE}`).then((timeline) => ({ timeline, timelineError: undefined }))
      .catch((failure) => ({ timeline: null, timelineError: errorText(failure) })),
  ]);
  if (!item.refund_case_id) return { item, ...log, payment: null, basis: null, approvals: [], executions: [] };
  const url = "/cases/" + item.refund_case_id;
  try {
    const [payment, basis, approvals, executions] = await Promise.all([
      request<LegacyCase>(url), request<Reconciliation>(url + "/reconciliation"), request<Approval[]>(url + "/refund-approvals"),
      request<Execution[]>(url + "/refund-executions"),
    ]);
    return { item, ...log, payment, basis, approvals, executions };
  } catch (failure) {
    return { item, ...log, payment: null, basis: null, approvals: [], executions: [], paymentError: errorText(failure) };
  }
}

export function Workspace({ mode, initialCaseId = null }: { mode: "demo" | "merchant"; initialCaseId?: string | null }) {
  const demo = mode === "demo";
  const [demoStore, setDemoStore] = useState(() => new DemoStore());
  const [merchant, setMerchant] = useState<Merchant | null>(null);
  const [sessionError, setSessionError] = useState("");
  const [inbox, setInbox] = useState(() => initialPage(demo ? demoStore.initial() : []));
  const [selected, setSelected] = useState<string | null>(demo ? demoPrimary : initialCaseId);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [tab, setTab] = useState<DeskTab>("overview");
  const [nav, setNav] = useState<Nav>("inbox");
  const [mobileCase, setMobileCase] = useState(Boolean(initialCaseId));
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [loadingList, setLoadingList] = useState(false);
  const [loadingTimeline, setLoadingTimeline] = useState(false);
  const [listError, setListError] = useState("");
  const [detailError, setDetailError] = useState("");
  const [actionError, setActionError] = useState("");
  const [refundNotice, setRefundNotice] = useState("");
  const [refreshing, setRefreshing] = useState<string | null>(null);
  const [paymentBusy, setPaymentBusy] = useState(false);
  const [toast, setToast] = useState("");
  const [reviews, setReviews] = useState<Page<Review>>({ items: [], total: 0, limit: 20, offset: 0 });
  const [reviewStatus, setReviewStatus] = useState<"open" | "resolved">("open");
  const [reviewError, setReviewError] = useState("");
  const [loadingReview, setLoadingReview] = useState(false);
  const detailSeq = useRef(0), inboxSeq = useRef(0), reviewSeq = useRef(0);
  const requestIds = useRef(new Map<string, string>());
  const request = demo ? demoStore.request : backendRequest;
  const closeDialog = () => setDialog(null);
  const current = detail?.item.id === selected ? detail : null;
  const item = current?.item ?? inbox.items.find((entry) => entry.id === selected);
  const refund = item?.promises.find((p) => p.terms.target.kind === "refund");

  const loadInbox = useCallback(async (offset = 0) => {
    const seq = ++inboxSeq.current;
    setLoadingList(true); setListError("");
    try {
      const result = demo ? await request<Page<CaseView>>(`/resolution-cases?limit=${CASE_PAGE}&offset=${offset}`)
        : await request<Page<CaseView>>("/resolution-cases/inbox?" + new URLSearchParams({
          limit: String(CASE_PAGE), offset: String(offset), filter_by: filter, q: search.trim(),
        }));
      const rows = demo ? await Promise.all(result.items.map((summary) => fetchSummary(request, summary.id))) : result.items;
      if (seq !== inboxSeq.current) return;
      setInbox((previous) => {
        const merged = offset ? [...previous.items, ...rows.filter((row) => !previous.items.some((item) => item.id === row.id))] : rows;
        return { ...result, items: merged };
      });
      if (!offset) setSelected((previous) => previous ?? rows[0]?.id ?? null);
    } catch (failure) { if (seq === inboxSeq.current) setListError(errorText(failure)); }
    finally { if (seq === inboxSeq.current) setLoadingList(false); }
  }, [demo, filter, request, search]);

  const updateOperations = useCallback((id: string, operations: Operations) => {
    setInbox((previous) => ({ ...previous, items: previous.items.map((row) => row.id === id ? { ...row, operations } : row) }));
    setDetail((previous) => previous?.item.id === id ? { ...previous, item: { ...previous.item, operations } } : previous);
  }, []);

  const loadDetail = useCallback(async (id: string) => {
    const seq = ++detailSeq.current;
    setDetailError("");
    try {
      const result = await fetchCase(request, id);
      if (seq !== detailSeq.current) return;
      setDetail(result);
      setInbox((previous) => ({ ...previous, items: previous.items.map((item) => item.id === id ? result.item : item) }));
    } catch (failure) {
      if (seq === detailSeq.current) { setDetail(null); setDetailError(errorText(failure)); }
    }
  }, [request]);

  const loadReview = useCallback(async (offset = 0) => {
    const seq = ++reviewSeq.current;
    setLoadingReview(true); setReviewError("");
    try {
      const result = await request<Page<Review>>(`/review-queue?status=${reviewStatus}&limit=20&offset=${offset}`);
      if (seq === reviewSeq.current) setReviews((previous) => ({ ...result, items: offset ? [...previous.items, ...result.items] : result.items }));
    } catch (failure) { if (seq === reviewSeq.current) setReviewError(errorText(failure)); }
    finally { if (seq === reviewSeq.current) setLoadingReview(false); }
  }, [request, reviewStatus]);

  useEffect(() => {
    if (demo) return;
    let enabled = true;
    fetch("/api/session", { cache: "no-store" }).then(readJson<Session>).then((value) => {
      if (!enabled) return;
      if (!value.merchant) { window.location.replace("/login"); return; }
      setMerchant(value.merchant);
    }).catch((failure) => { if (enabled) setSessionError(errorText(failure)); });
    return () => { enabled = false; };
  }, [demo]);

  useEffect(() => {
    if (!merchant) { if (demo) void loadInbox(); return; }
    inboxSeq.current += 1;
    const timer = window.setTimeout(() => void loadInbox(), search ? 150 : 0);
    return () => window.clearTimeout(timer);
  }, [demo, merchant, loadInbox, search]);
  useEffect(() => { if (selected) void loadDetail(selected); }, [selected, loadDetail]);
  useEffect(() => { if (nav === "review") void loadReview(); }, [nav, loadReview]);
  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 5000);
    return () => window.clearTimeout(timer);
  }, [toast]);

  function setMode(next: Merchant | null) {
    detailSeq.current += 1; inboxSeq.current += 1; reviewSeq.current += 1;
    requestIds.current.clear();
    setMerchant(next); setDetail(null); setSelected(next ? null : demoPrimary);
    setInbox(initialPage(next ? [] : demoStore.initial())); setListError(""); setActionError("");
    setDetailError(""); setRefundNotice(""); setTab("overview"); setFilter("all"); setSearch("");
    setMobileCase(false); setNav("inbox"); setReviews({ items: [], total: 0, limit: 20, offset: 0 });
  }

  function select(id: string) {
    if (id !== selected) { detailSeq.current += 1; setDetail(null); }
    setNav("inbox"); setSelected(id); setTab("overview"); setMobileCase(true);
    setActionError(""); setDetailError(""); setRefundNotice("");
  }

  async function connect(token: string) {
    const result = await readJson<Session>(await fetch("/api/session", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token }),
    }));
    if (!result.merchant) throw new Error("Resolve did not return a merchant workspace.");
    window.location.assign("/workspace");
  }

  async function disconnect() {
    try {
      await readJson<Session>(await fetch("/api/session", { method: "DELETE" }));
      window.location.assign("/login");
    } catch (failure) { setToast(errorText(failure)); }
  }

  function resetDemo() {
    const next = new DemoStore();
    setMode(null); setDemoStore(next); setInbox(initialPage(next.initial())); setToast("Demo reset.");
  }

  function onCreated(value: CaseView) {
    setInbox((previous) => ({ ...previous, total: previous.total + 1, items: [value, ...previous.items] }));
    setFilter("all"); setSearch(""); select(value.id); closeDialog(); setToast("Resolution case created.");
  }

  async function savePromise(terms: Terms, edit?: PromiseView) {
    if (!item) return;
    const base = `/resolution-cases/${item.id}/promises`;
    await request(edit ? base + "/" + edit.id : base, edit ? "PUT" : "POST", edit ? { ...terms, expected_revision: edit.revision } : terms);
    closeDialog(); setToast(edit ? "Promise revised." : "Promise recorded."); await loadDetail(item.id);
  }

  async function saveEvidence(promise: PromiseView, data: unknown) {
    if (!item) return;
    await request(`/resolution-cases/${item.id}/promises/${promise.id}/evidence`, "POST", data);
    closeDialog(); setToast("Evidence recorded."); await loadDetail(item.id);
  }

  async function checkProvider(promise: PromiseView) {
    if (!item || refreshing) return;
    setRefreshing(promise.id); setActionError("");
    try {
      await request(`/resolution-cases/${item.id}/promises/${promise.id}/refresh`, "POST", { expected_revision: promise.revision });
      setToast(demo ? "Simulated evidence refreshed." : "Provider evidence refreshed.");
    } catch (failure) { setActionError(errorText(failure)); }
    finally { await loadDetail(item.id); setRefreshing(null); }
  }

  async function nextEvents() {
    if (!item || !current?.timeline || loadingTimeline) return;
    const prior = current.timeline;
    const id = item.id, seq = detailSeq.current;
    setLoadingTimeline(true);
    try {
      const next = await request<Timeline>(`/resolution-cases/${id}/timeline?limit=${EVENT_PAGE}&offset=${prior.offset + prior.limit}`);
      if (seq === detailSeq.current) setDetail((value) => value?.item.id === id ? {
        ...value, timelineError: undefined,
        timeline: { ...next, items: [...prior.items, ...next.items], refund_items: [...prior.refund_items, ...next.refund_items] },
      } : value);
    } catch (failure) {
      if (seq === detailSeq.current) setDetail((value) => value ? { ...value, timelineError: errorText(failure) } : null);
    } finally { setLoadingTimeline(false); }
  }

  async function exportEvidence() {
    if (!item) return;
    try {
      const result = await request(`/resolution-cases/${item.id}/evidence-bundle?limit=100`);
      const href = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: "application/json" }));
      const link = document.createElement("a");
      link.href = href; link.download = `resolve-evidence-${shortId(item.id)}.json`; link.click();
      window.setTimeout(() => URL.revokeObjectURL(href), 1000);
      setToast("Evidence export downloaded.");
    } catch (failure) { setActionError(errorText(failure)); }
  }

  const paymentBasis = current?.basis ?? null;
  const active = activeApproval(current?.approvals ?? [], current?.executions ?? [], paymentBasis);
  const latestExecution = current?.executions[0];
  const canReview = !!current?.payment && paymentBasis?.status === "refund_required"
    && paymentBasis.paypal_history_current && Number(paymentBasis.recommended_refund_amount) > 0;
  const canSubmit = canReview && !!active;
  const nextMessage = paymentBasis
    ? paymentBasis.status === "refund_required" && !paymentBasis.paypal_history_current ? "Check current PayPal history before approving an exact amount." : reconcileLabels[paymentBasis.status] ?? pretty(paymentBasis.next_action)
    : "Read the payment evidence to see the next step.";

  async function reviewRefund(prefill?: string) {
    if (!item?.refund_case_id) return;
    setPaymentBusy(true); setActionError("");
    try {
      const basis = await request<Reconciliation>(`/cases/${item.refund_case_id}/reconciliation`);
      if (basis.status !== "refund_required" || !basis.paypal_history_current || Number(basis.recommended_refund_amount) <= 0) {
        await loadDetail(item.id);
        throw new Error("The evidence changed. Review the current case before approving.");
      }
      // A suggested amount only pre-fills the form, and never above the backend's current cap.
      const capped = prefill && (amountCents(prefill) ?? 0) <= (amountCents(basis.recommended_refund_amount) ?? 0) ? prefill : undefined;
      setDialog({ kind: "approve", basis, prefill: capped });
    } catch (failure) { setActionError(errorText(failure)); }
    finally { setPaymentBusy(false); }
  }

  function requestId(key: string) {
    const original = requestIds.current.get(key);
    if (original) return original;
    const id = uuid();
    requestIds.current.set(key, id);
    return id;
  }

  async function approveRefund(basis: Reconciliation, note: string, requested: string) {
    if (!item?.refund_case_id || !current?.payment) return;
    const root = `/cases/${item.refund_case_id}`;
    const fresh = await request<Reconciliation>(root + "/reconciliation");
    if (fresh.state_fingerprint !== basis.state_fingerprint || fresh.status !== "refund_required" || !fresh.paypal_history_current ||
      fresh.recommended_refund_amount !== basis.recommended_refund_amount) {
      await loadDetail(item.id);
      throw new Error("The refund evidence changed. Close this review and check the current amount.");
    }
    await request<Approval>(root + "/refund-approvals", "POST", {
      request_id: requestId(`approve:${root}:${basis.state_fingerprint}:${requested}:${note}`), capture_id: current.payment.payment.capture_id,
      amount: requested, currency: basis.currency, state_fingerprint: basis.state_fingerprint, decision_note: note,
    });
    closeDialog(); setToast("Approval recorded. No refund has been submitted."); await loadDetail(item.id);
  }

  async function executeRefund(approval: Approval) {
    if (!item?.refund_case_id) return;
    try {
      const execution = await request<Execution>(`/cases/${item.refund_case_id}/refund-executions`, "POST", {
        request_id: requestId("submit:" + approval.id), approval_id: approval.id,
      });
      closeDialog(); setToast(execution.status === "completed" && execution.provider_refund?.provider_status === "COMPLETED"
        ? demo ? "Demo refund confirmed." : "PayPal Sandbox confirmed the refund."
        : `Submission status: ${pretty(execution.status)}. Check the timeline before taking another action.`);
    } finally { await loadDetail(item.id); }
  }

  async function checkExecution() {
    if (!item?.refund_case_id || !latestExecution?.provider_refund?.refund_id) return;
    setPaymentBusy(true); setActionError("");
    try {
      const result = await request<Execution>(`/cases/${item.refund_case_id}/refund-executions/${latestExecution.id}/refresh`, "POST",
        { refund_id: latestExecution.provider_refund.refund_id });
      setToast(`PayPal Sandbox status: ${pretty(result.status)}.`);
    } catch (failure) { setActionError(errorText(failure)); }
    finally { await loadDetail(item.id); setPaymentBusy(false); }
  }

  async function simulateOutsideRefund() {
    try {
      demoStore.simulateExternal();
      await loadDetail(demoPrimary);
      setRefundNotice("Duplicate refund blocked. An outside refund covered the balance, so the previous approval is no longer valid.");
    } catch (failure) { setActionError(errorText(failure)); }
  }

  const desk = item && <CaseDesk item={item} tab={tab} setTab={setTab} request={request} demo={demo} onBack={() => setMobileCase(false)}
    assistant={demo ? undefined : <div className="ai-stack" aria-label="AI and promise checks">
      <PromiseExtractionPanel key={"extract-" + item.id} caseId={item.id} request={request} onUse={(draft) => setDialog({ kind: "promise", draft })} />
      <PromiseHealthPanel key={"health-" + item.id} caseId={item.id} request={request}
        refreshKey={current?.basis?.state_fingerprint} canRefund={canReview && !active && !paymentBusy} blockedReason={active ? "an approval is already recorded." : nextMessage}
        onRefund={(amount) => void reviewRefund(amount)} />
      <InvestigationReviewPanel key={item.id} caseId={item.id} request={request} />
    </div>}
    onLinkPayment={() => setDialog({ kind: "payment-link", item })}
    onManage={() => item.operations && setDialog({ kind: "operations", id: item.id, fields: item.operations })}
    onOperations={updateOperations}
    timeline={current?.timeline ?? null} timelineError={current?.timelineError} loadMore={nextEvents} loadingTimeline={loadingTimeline}
    onAdd={() => setDialog({ kind: "promise" })} onEdit={(edit) => setDialog({ kind: "promise", edit })}
    onEvidence={(promise) => setDialog({ kind: "evidence", promise })} onRefresh={checkProvider} onExport={exportEvidence}
    refreshing={refreshing} error={detailError || actionError} verifiedMessage={refundNotice}
    payment={{ basis: paymentBasis, approval: active, execution: latestExecution, nextMessage, canReview, canSubmit,
      busy: paymentBusy || !!refreshing || !current, error: current?.paymentError, onReview: () => void reviewRefund(),
      onSubmit: () => active && setDialog({ kind: "execute", approval: active }),
      onRefresh: () => refund && void checkProvider(refund), onCheckExecution: checkExecution,
      onSimulateOutside: demo && item.id === demoPrimary ? simulateOutsideRefund : undefined }} />;

  if (!demo && !merchant) return <main className="access-shell access-empty">
    <section className="access-card"><Link href="/" aria-label="Resolve home"><Brand /></Link>
      <h1>{sessionError ? "Could not open your workspace" : "Opening your workspace…"}</h1>
      {sessionError && <><Notice>{sessionError}</Notice><Button onClick={() => window.location.reload()}>Retry</Button></>}
    </section>
  </main>;

  return <div className="app-shell">
    <a className="skip-link" href="#workspace-content">Skip to workspace</a>
    <aside className="sidebar" aria-label="Workspace navigation">
      <div className="sidebar-brand"><Link href="/" aria-label="Resolve home"><Brand /></Link><span>MERCHANT WORKSPACE</span></div>
      <div className="sidebar-group"><div className="sidebar-label">WORKSPACE</div>
        <button type="button" aria-label="Case inbox" className={nav === "inbox" ? "rail-active" : ""} onClick={() => { setNav("inbox"); setMobileCase(false); }} aria-current={nav === "inbox" ? "page" : undefined}>
          <Inbox size={18} /> <span>Case inbox</span><ChevronRight className="rail-chevron" size={15} /></button>
        {!demo && <Link href="/workspace/orders" className="rail-link"><Package size={18} /> <span>Orders</span><ChevronRight className="rail-chevron" size={15} /></Link>}
        <button type="button" aria-label="Review queue" className={nav === "review" ? "rail-active" : ""} onClick={() => { setNav("review"); setMobileCase(false); }} aria-current={nav === "review" ? "page" : undefined}>
          <ClipboardList size={18} /> <span>Review queue</span><ChevronRight className="rail-chevron" size={15} /></button>
      </div>
      <div className="sidebar-bottom"><div className="sidebar-mode"><span className="sidebar-mode-icon"><ShieldCheck size={19} /></span>
        <div><strong>{demo ? "Demo workspace" : "Sandbox connection"}</strong><p>{demo ? "Sample records. No money moves." : "Local merchant account connected."}</p></div></div>
        <button type="button" aria-label="Workspace guide" onClick={() => setDialog({ kind: "guide" })}><BookOpen size={17} /><span>Workspace guide</span></button>
      </div>
    </aside>
    <main id="workspace-content" className="main-pane">
      <header className="topbar">
        <div className="topbar-crumb"><span>Workspace</span><ChevronRight size={14} /><strong>{nav === "inbox" ? "Resolution cases" : "Review queue"}</strong></div>
        <div className="mobile-brand"><Brand small /></div>
        <div className="topbar-actions">
          <span className="mode-chip"><span />{demo ? "Demo mode" : "Connected · Sandbox"}</span>
          {demo ? <Button onClick={() => setDialog({ kind: "connect" })} className="connect-button"><Link2 size={16} /><span>Connect account</span></Button>
            : <><Link href="/workspace/settings" className="button button-secondary connect-button" aria-label="Account settings" title="Account settings"><Settings2 size={16} /><span>Settings</span></Link>
              <Button onClick={disconnect} className="connect-button" aria-label="Sign out" title="Sign out"><LogOut size={16} /><span>Sign out</span></Button></>}
          <span className="avatar" aria-label={merchant?.name ?? "Demo merchant"}>{(merchant?.name ?? "Demo Merchant").split(/\s+/).slice(0, 2).map((part) => part.charAt(0).toUpperCase()).join("")}</span>
        </div>
      </header>
      <div className="mobile-nav" aria-label="Mobile navigation">
        <Button variant={nav === "inbox" ? "primary" : "ghost"} onClick={() => { setNav("inbox"); setMobileCase(false); }}><Inbox size={16} /> Inbox</Button>
        {!demo && <Link href="/workspace/orders" className="button button-ghost"><Package size={16} /> Orders</Link>}
        <Button variant={nav === "review" ? "primary" : "ghost"} onClick={() => setNav("review")}><ClipboardList size={16} /> Review queue</Button>
      </div>
      <div className="workspace">
        <div className="workspace-intro">
          <div><div className="eyebrow intro-eyebrow"><span /> MERCHANT OPERATIONS</div>
            <h1>{nav === "inbox" ? "Resolution workspace" : "Review queue"}</h1>
            <p>{nav === "inbox" ? "Track promises, verify outcomes, and resolve every case with evidence." : "Follow up on cases that need a closer look."}</p></div>
          <div className="intro-actions"><Button variant="ghost" className="icon-button reload-button" aria-label="Reload workspace" title="Reload workspace"
            onClick={() => { if (nav === "review") void loadReview(); else { void loadInbox(); if (selected) void loadDetail(selected); } }} disabled={loadingList || loadingReview}><RefreshCw size={18} /></Button>
            <Button onClick={() => setDialog({ kind: "invite" })}><Link2 size={17} /> Invite customer</Button>
            <Button variant="primary" onClick={() => setDialog({ kind: "case" })}><Plus size={18} /> New case</Button></div>
        </div>
        {nav === "inbox" ? <>
          <StatusMetrics cases={inbox.items} total={inbox.total} />
          {listError && <Notice>{listError} <button type="button" className="inline-link" onClick={() => loadInbox()}>Try again</button></Notice>}
          <div className={`case-board ${mobileCase && item ? "mobile-detail" : ""}`}>
            <InboxPane cases={inbox.items} selected={selected} select={select} filter={filter} setFilter={setFilter} search={search}
              setSearch={setSearch} more={inbox.offset + CASE_PAGE < inbox.total} onMore={() => loadInbox(inbox.offset + CASE_PAGE)}
              loading={loadingList} onNew={() => setDialog({ kind: "case" })} demo={demo} />
            <div className="desk-pane">{desk || <Empty title={loadingList ? "Loading case workspace…" : "Select a case"} detail={loadingList ? "Reading your cases from the local backend." : "Open a case from the inbox to see its promises and evidence."} />}</div>
          </div>
          {demo && <div className="demo-tools"><span><FlaskConical size={17} /> Demo controls</span><p>Try the normal refund, or approve first and simulate a refund made outside Resolve.</p>
            <a className="button button-secondary small-button" href="/customer?demo=1" target="_blank" rel="noreferrer">Customer demo</a>
            <Button className="small-button" variant="ghost" onClick={resetDemo}>Reset demo</Button></div>}
        </> : <ReviewPane items={reviews.items} total={reviews.total} status={reviewStatus} setStatus={(status) => {
          reviewSeq.current += 1; setReviews({ items: [], total: 0, limit: 20, offset: 0 }); setReviewStatus(status);
        }} loading={loadingReview} error={reviewError} onMore={() => loadReview(reviews.offset + reviews.limit)} cases={inbox.items}
          onOpen={select} onResolve={(review) => setDialog({ kind: "review", item: review })} />}
        <footer className="workspace-footer"><span>Resolve · Payment aftercare</span><button type="button" onClick={() => setDialog({ kind: "guide" })}>Workspace guide <ChevronRight size={13} /></button></footer>
      </div>
    </main>
    {toast && <div className="toast" role="status"><span><CheckCircle2 size={17} /></span>{toast}<Button variant="ghost" className="icon-button" aria-label="Dismiss message" onClick={() => setToast("")}><X size={16} /></Button></div>}
    {dialog?.kind === "connect" && <ConnectForm onClose={closeDialog} onConnect={connect} />}
    {dialog?.kind === "guide" && <LocalGuide onClose={closeDialog} />}
    {dialog?.kind === "case" && <CaseForm onClose={closeDialog} request={request} onSaved={onCreated} />}
    {dialog?.kind === "invite" && <InviteForm onClose={closeDialog} request={request} demo={demo} />}
    {dialog?.kind === "payment-link" && <PaymentLinkForm item={dialog.item} onClose={closeDialog} request={request} onSaved={() => {
      closeDialog(); setToast("Payment record linked."); void loadDetail(dialog.item.id);
    }} />}
    {dialog?.kind === "operations" && <OperationsForm current={dialog.fields} onClose={closeDialog} onSave={async (data) => {
      try {
        const ops = await request<Operations>("/resolution-cases/" + dialog.id + "/operations", "PUT", data);
        updateOperations(dialog.id, ops); closeDialog(); setToast("Case settings saved.");
      } catch (failure) {
        if (failure instanceof ApiError && failure.status === 409) {
          closeDialog(); void loadDetail(dialog.id); setToast("Case settings changed. Review the latest values and try again.");
        } else throw failure;
      }
    }} />}
    {dialog?.kind === "promise" && item && <PromiseForm item={item} edit={dialog.edit} draft={dialog.draft} linkedPayment={current?.payment} onClose={closeDialog} onSave={savePromise} />}
    {dialog?.kind === "evidence" && <EvidenceForm promise={dialog.promise} onClose={closeDialog} onSave={(data) => saveEvidence(dialog.promise, data)} />}
    {dialog?.kind === "approve" && <RefundForm amount={dialog.basis.recommended_refund_amount} initial={dialog.prefill} demo={demo}
      onClose={closeDialog} onApprove={(note, requested) => approveRefund(dialog.basis, note, requested)} onExecute={executeRefund} />}
    {dialog?.kind === "execute" && <RefundForm amount={dialog.approval.amount} approval={dialog.approval} demo={demo}
      onClose={closeDialog} onApprove={async () => { throw new ApiError(409, "This approval is already recorded."); }} onExecute={executeRefund} />}
    {dialog?.kind === "review" && <ReviewForm onClose={closeDialog} onSave={async (reason) => {
      await request("/review-queue/" + dialog.item.id + "/resolve", "POST", { reason });
      closeDialog(); setToast("Review item resolved."); await loadReview();
    }} />}
  </div>;
}
