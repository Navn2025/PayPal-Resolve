"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowRight, ChevronLeft, ChevronRight, Inbox, Link2, Package, RefreshCw, Search, Settings2 } from "lucide-react";
import { backendRequest } from "@/lib/http";
import { dateText, money, pretty, timeText } from "@/lib/domain";
import { Brand, Button, Empty, Notice } from "./ui";

type Payment = {
  status: string | null; captured_amount: string | null; refunded_amount: string | null;
  paypal_order_id: string | null; paypal_capture_id: string | null;
};
type Order = {
  id: string; case_id: string | null; source: string; order_reference: string;
  synced_at: string; order_status: string | null; payment: Payment | null; line_count: number;
};
type Page = { items: Order[]; total: number; limit: number; offset: number };
type Snapshot = {
  id: string; case_id: string | null; source: string; order_reference: string; synced_at: string;
  app: { order_status: string | null; payment: Payment | null; items: {
    product_id: string; name: string | null; sku: string | null; quantity: number; unit_amount: string | null;
  }[] };
};
type Check = {
  status: "match" | "mismatch" | "incomplete";
  last_checked_at: string | null;
  provider_issues: { detail: string }[];
  checks: { field: string; status: string; app_value: string | null; paypal_value: string | null }[];
};
const SIZE = 20;
const base = "/commerce/orders";
const message = (error: unknown) => error instanceof Error ? error.message : "Try again shortly.";
const amount = (value: string | null | undefined) => value == null ? "—" : money(value);

export function MerchantOrders() {
  const [draft, setDraft] = useState({ q: "", source: "" });
  const [query, setQuery] = useState(draft);
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [page, setPage] = useState<Page | null>(null);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<Snapshot | null>(null);
  const [check, setCheck] = useState<Check | null>(null);
  const [detailError, setDetailError] = useState("");
  const [busy, setBusy] = useState(false);
  const requestId = useRef(0);

  useEffect(() => {
    let active = true;
    const params = new URLSearchParams({ limit: String(SIZE), offset: String(offset), ...query });
    backendRequest<Page>(base + "?" + params).then((value) => {
      if (!active) return;
      setPage(value);
      if (offset > 0 && value.items.length === 0 && value.total <= offset) {
        setOffset(Math.max(0, Math.floor((value.total - 1) / SIZE) * SIZE));
      }
    }).catch((error) => { if (active) setListError(message(error)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [query, offset, refresh]);

  function reload() {
    setListError("");
    setLoading(true);
    setRefresh((value) => value + 1);
  }

  async function select(id: string) {
    const sequence = ++requestId.current;
    setSelected(id); setDetail(null); setCheck(null); setDetailError(""); setBusy(false);
    try {
      const order = await backendRequest<Snapshot>(base + "/" + id);
      if (sequence !== requestId.current) return;
      setDetail(order);
      if (order.case_id) {
        const report = await backendRequest<Check>("/resolution-cases/" + order.case_id + "/commerce");
        if (sequence === requestId.current) setCheck(report);
      }
    } catch (error) { if (sequence === requestId.current) setDetailError(message(error)); }
  }

  async function openCase() {
    if (!detail || busy) return;
    const sequence = requestId.current;
    setBusy(true); setDetailError("");
    try {
      const receipt = await backendRequest<{ case_id: string }>(base + "/" + detail.id + "/case", "POST");
      reload();
      if (sequence === requestId.current) setDetail({ ...detail, case_id: receipt.case_id });
    } catch (error) { if (sequence === requestId.current) setDetailError(message(error)); }
    finally { if (sequence === requestId.current) setBusy(false); }
  }

  async function checkPayPal() {
    if (!detail?.case_id || busy) return;
    const sequence = requestId.current;
    setBusy(true); setDetailError("");
    try {
      const report = await backendRequest<Check>("/resolution-cases/" + detail.case_id + "/commerce/refresh", "POST");
      if (sequence === requestId.current) setCheck(report);
    } catch (error) { if (sequence === requestId.current) setDetailError(message(error)); }
    finally { if (sequence === requestId.current) setBusy(false); }
  }

  return <div className="app-shell">
    <a className="skip-link" href="#orders-content">Skip to orders</a>
    <aside className="sidebar" aria-label="Workspace navigation">
      <div className="sidebar-brand"><Link href="/" aria-label="Resolve home"><Brand /></Link><span>MERCHANT WORKSPACE</span></div>
      <div className="sidebar-group"><div className="sidebar-label">WORKSPACE</div>
        <Link href="/workspace" className="rail-link"><Inbox size={18} /><span>Case inbox</span></Link>
        <Link href="/workspace/orders" className="rail-link rail-active" aria-current="page"><Package size={18} /><span>Orders</span></Link>
        <Link href="/workspace/settings" className="rail-link"><Settings2 size={18} /><span>Settings</span></Link>
      </div>
    </aside>
    <main id="orders-content" className="main-pane">
      <header className="topbar"><div className="topbar-crumb"><Link href="/workspace">Workspace</Link><ChevronRight size={15} /><strong>Orders</strong></div>
        <Button className="small-button" onClick={reload} disabled={loading}><RefreshCw size={15} /> Refresh orders</Button>
      </header>
      <div className="workspace">
        <div className="workspace-intro"><div><div className="eyebrow intro-eyebrow"><span /> CONNECTED COMMERCE</div><h1>Orders</h1>
          <p>Browse orders from your apps and open a resolution case when an order needs attention.</p></div></div>
        <details className="section-card order-setup">
          <summary><Link2 size={16} /> Connect an app or import existing orders</summary>
          <p><Link href="/workspace/settings#sdk-keys">Generate an SDK key in Settings</Link>, then copy the server setup into your app. Set a stable source name, such as <code>my-store</code>.</p>
          <p>Use <code>createResolve().syncOrder(order)</code> for each order or <code>connectPostgres(pool).registerAll()</code> to import your app&apos;s existing PostgreSQL orders. Send new revisions as orders change.</p>
        </details>
        <div className="order-board">
          <section className="section-card order-list" aria-label="Synced orders" aria-busy={loading}>
            <form className="order-filters" onSubmit={(event) => {
              event.preventDefault(); setOffset(0); setQuery({ q: draft.q.trim(), source: draft.source.trim() }); reload();
            }}>
              <label className="field"><span>Search orders</span><input placeholder="Order or PayPal ID" maxLength={160}
                value={draft.q} onChange={(event) => setDraft({ ...draft, q: event.target.value })} /></label>
              <label className="field"><span>App source</span><input placeholder="All apps" maxLength={64}
                value={draft.source} onChange={(event) => setDraft({ ...draft, source: event.target.value })} /></label>
              <Button type="submit" className="small-button"><Search size={15} /> Search</Button>
            </form>
            {listError && <Notice>{listError}</Notice>}
            {!listError && (!page?.items.length ? <Empty
              title={loading ? "Loading orders…" : query.q || query.source ? "No matching orders" : "No orders synced yet"}
              detail={loading ? "Reading your merchant workspace." : query.q || query.source ? "Try a different order reference or app source." : "Connect an app and import orders to see them here."}
            /> : <>
              <p className="order-count" aria-live="polite">{page.offset + 1}–{page.offset + page.items.length} of {page.total} orders</p>
              <div className="order-rows">{page.items.map((order) => <button type="button" key={order.id} onClick={() => void select(order.id)}
                className={"order-row " + (selected === order.id ? "selected" : "")} aria-current={selected === order.id ? "true" : undefined}>
                <span className="order-icon"><Package size={16} /></span>
                <span className="order-row-meta"><strong>{order.order_reference}</strong><small>{order.source} · {order.line_count} lines · {dateText(order.synced_at)}</small></span>
                <span className="order-row-status"><strong>{amount(order.payment?.captured_amount)}</strong><small>{order.case_id ? "Case linked" : order.payment?.status ? pretty(order.payment.status) : "No case"}</small></span>
                <ChevronRight size={15} />
              </button>)}</div>
              <div className="order-paging"><Button className="small-button" disabled={loading || offset === 0} onClick={() => { setOffset(Math.max(0, offset - SIZE)); reload(); }}><ChevronLeft size={15} /> Previous</Button>
                <Button className="small-button" disabled={loading || offset + SIZE >= page.total} onClick={() => { setOffset(offset + SIZE); reload(); }}>Next <ChevronRight size={15} /></Button></div>
            </>)}
          </section>
          <section className="section-card order-detail" aria-label="Order details">
            {detailError && <Notice>{detailError}</Notice>}
            {!detail ? <Empty title={selected ? detailError ? "Could not open order" : "Loading order…" : "Select an order"}
              detail="See what your app reported, then open a case to verify PayPal evidence." />
              : <>
                <div className="eyebrow">APP-REPORTED ORDER</div><h2>{detail.order_reference}</h2>
                <p className="muted">{detail.source} · Last synced {timeText(detail.synced_at)}</p>
                <dl className="order-data">
                  <div><dt>Order status</dt><dd>{detail.app.order_status ?? "Not supplied"}</dd></div>
                  <div><dt>Payment status</dt><dd>{detail.app.payment?.status ? pretty(detail.app.payment.status) : "Not supplied"}</dd></div>
                  <div><dt>Captured amount</dt><dd>{amount(detail.app.payment?.captured_amount)}</dd></div>
                  <div><dt>Refunded amount</dt><dd>{amount(detail.app.payment?.refunded_amount)}</dd></div>
                  <div><dt>PayPal order</dt><dd>{detail.app.payment?.paypal_order_id ?? "Not supplied"}</dd></div>
                  <div><dt>PayPal capture</dt><dd>{detail.app.payment?.paypal_capture_id ?? "Not supplied"}</dd></div>
                </dl>
                <h3>Line items</h3>
                {detail.app.items.length ? <ul className="order-items">{detail.app.items.map((item, index) =>
                  <li key={item.product_id + ":" + index}><span>{item.name || item.product_id}{item.sku ? " · " + item.sku : ""}</span>
                    <strong>{item.quantity} × {amount(item.unit_amount)}</strong></li>)}</ul> : <p className="muted">No line items supplied.</p>}
                <div className="order-actions">
                  {detail.case_id ? <>
                    <Link className="button button-primary small-button" href={"/workspace?case=" + detail.case_id}>Open case <ArrowRight size={15} /></Link>
                    <Button className="small-button" onClick={() => void checkPayPal()} disabled={busy}>{busy ? "Checking…" : "Check PayPal evidence"}</Button>
                  </> : <Button variant="primary" className="small-button" onClick={() => void openCase()} disabled={busy}>{busy ? "Opening…" : "Create resolution case"}</Button>}
                </div>
                {check && <div className="order-evidence" aria-live="polite">
                  <h3>{check.status === "match" ? "Matched PayPal" : check.status === "mismatch" ? "Differences found" : "Needs more evidence"}</h3>
                  {check.last_checked_at && <p className="muted">Checked {timeText(check.last_checked_at)}</p>}
                  <ul className="order-items">{check.checks.map((row) => <li key={row.field}>
                    <span>{pretty(row.field)}</span><strong>{pretty(row.status)}{row.status === "mismatch" ? " · App " + (row.app_value ?? "—") + " / PayPal " + (row.paypal_value ?? "—") : ""}</strong></li>)}</ul>
                  {check.provider_issues.map((issue, index) => <p className="muted" key={index}>{issue.detail}</p>)}
                </div>}
              </>}
          </section>
        </div>
      </div>
    </main>
  </div>;
}
