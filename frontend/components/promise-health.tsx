"use client";

import { Notice } from "./ui";
import { dueLabel, days, statusBadge, statusLabels, type CaseChecks } from "./case-checks";

/** One line per accepted refund promise. Amounts live in the money summary; this shows status and timing only. */
export function PromiseCheckList({ checks, paused = false }: { checks: CaseChecks; paused?: boolean }) {
  const { health, next, error, loading } = checks;
  return <section className="section-card promise-health" aria-label="Promise check" aria-busy={loading}>
    <div className="section-head"><div><div className="eyebrow">Broken-promise check</div><h3>Promise check</h3></div></div>
    {error && <Notice>{error}</Notice>}
    {loading && <p className="panel-state" role="status">Checking promises…</p>}
    {health && !health.items.length && (paused
      ? <p className="panel-state check-paused">Paused – promise needs review</p>
      : <p className="panel-state">No accepted refund promise on a linked payment to check.</p>)}
    {!!health?.items.length && <ul className="check-list">{health.items.map((item) => {
      const due = dueLabel(item, health, next);
      return <li key={item.promise_id} className={`check-row health-${item.status}`} aria-label={`Promise ${statusLabels[item.status]}`}>
        <span className="check-text">{item.promise}</span>
        <span className="check-meta">
          {due.text && <span className="due-label" title={due.rule}>{due.text}</span>}
          {item.status !== "kept" && <span>{days(item.days_since_promise)} since promise</span>}
          <span className={`badge ${statusBadge[item.status]}`}><span />{statusLabels[item.status]}</span>
        </span>
        {item.ledger_ahead_of_provider && <Notice tone="info">More refunds are recorded on the payment than PayPal has confirmed. Check the evidence before refunding again.</Notice>}
      </li>;
    })}</ul>}
    {!!health?.items.some((item) => item.status !== "kept") && <p className="card-note">Amounts are in the money summary at the top of the case.</p>}
  </section>;
}
