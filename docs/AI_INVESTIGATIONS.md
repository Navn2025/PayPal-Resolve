# Automatic investigations

## Audit and implementation plan (2026-11-08)

Usable: FastAPI `/resolution-cases`, `/resolution-cases/upsert`, evidence
`records`, `events`, `refresh`, evidence-bundle and cursor timeline; merchant
bearer/browser identity; transactional SQLite/PostgreSQL stores; separate refund
approval/execution; independent recovery/follow-up workers. SDK methods actually
present: createCase, upsertCase, linkRecord, addEvidence, refreshEvidence, getCase,
getTimeline, getEvidenceBundle, syncOrder. Commerce and sign-in changes already
in the working tree are preserved. Provider observations preserve prior facts
when a refresh fails. Partial: connectors need account-backed verification and
workers need an operator. Missing before this change: model adapters, automatic
investigation queue, structured recommendations and human investigation review.

1. Entry point: transactional enqueue on resolution creation and relevant
   evidence writes; coalesce repeated requests by revision. Use a separate
   bounded worker, with leases and revision checks, never inference in requests.
2. Evidence: owned resolution events, linked records, structured merchant
   approval claims, independently verified PayPal Sandbox facts and freshness,
   linked legacy payment reconciliation. Free text and contacts stay local.
3. Groq selects issue/read/escalation; OpenRouter investigates ambiguous cases.
   Server validates citations and builds factual findings; model output grants
   no authority. Unavailable inference produces a blocked reviewable result.
4. Approval boundary: full merchant identity reviews a revision and snapshot.
   Investigation approval is advisory and never creates a refund approval.
5. Acceptance: labeled synthetic refund states and adversarial cases; automatic
   queueing, duplicate/coalesced triggers, leased workers, bounded retries and
   reads, stale/concurrent/repeated review, failed refresh preservation, tenant
   isolation, forged citations, injection and no financial side effects.

Implementation details, model policy, commands and validation follow below.

## Model decision and official evidence

Catalogs/documentation were checked on 2026-11-08 using public, unauthenticated
pages. This is capability research, not account-backed inference validation.

| Candidate and route | Structured output | Published input/output USD per million tokens | Decision |
| --- | --- | --- | --- |
| Groq `openai/gpt-oss-20b`, direct Groq | Strict JSON schema | 0.075 / 0.30 | Default triage and linked-read selection |
| Groq `openai/gpt-oss-120b`, direct Groq | Strict JSON schema | 0.15 / 0.60 | Configurable triage comparison; greater cost |
| OpenRouter `anthropic/claude-sonnet-5.5`, `anthropic` | Endpoint lists `structured_outputs`, `response_format`, `max_tokens`, `reasoning_effort` | 2 / 10 | Final default selective deeper investigation |
| OpenRouter `anthropic/claude-sonnet-4.5`, `anthropic` | Endpoint lists `structured_outputs`, `response_format`, `max_tokens` | 3 / 15 | Provisional choice retained for comparison |
| OpenRouter `openai/gpt-4.1-mini`, `openai` | Endpoint lists structured outputs and response format | 0.40 / 1.60 | Lower-cost synthetic evaluation candidate |

[Groq's catalog](https://console.groq.com/docs/models) lists 20B throughput at
1000 tokens/second and 120B at 500; these are advertised throughput, not measured
request latency. Triage requests use the documented `low` reasoning effort
([Groq API reference](https://console.groq.com/docs/api-reference)).
The listed developer limits are 250K TPM/1K RPM for both;
[account and model limits](https://console.groq.com/docs/rate-limits) can differ.
[Strict output support](https://console.groq.com/docs/structured-outputs) is
documented for both. We select 20B for small, bounded decisions and reserve a
different provider/model family for ambiguous review. No evidence here proves
one model grounds evidence or abstains better than another.

OpenRouter's public [Sonnet 5.5 route catalog](https://openrouter.ai/api/v1/models/anthropic/claude-sonnet-5.5/endpoints)
confirms the exact Anthropic endpoint and required parameters. The final default
supersedes the provisional 4.5 choice: its published token prices are lower and
the required schema parameters are present. We use `low` reasoning effort to
bound this stage. This is a capability/cost choice, not measured quality.
The [Sonnet 4.5 route catalog](https://openrouter.ai/api/v1/models/anthropic/claude-sonnet-4.5/endpoints)
supports the retained baseline. Other advertised
routes include Azure, AWS, Google and regional variants; they are excluded by
default. The [4.1 Mini route catalog](https://openrouter.ai/api/v1/models/openai/gpt-4.1-mini/endpoints)
confirms the OpenAI and Azure alternatives. Compare all candidates on the fixed
rubric before enabling inference; published model descriptions establish no
quality ordering here. [OpenRouter limits](https://openrouter.ai/docs/api/reference/limits)
depend on the key/account and upstream; no account quota was read in this run.

[OpenRouter structured output documentation](https://openrouter.ai/docs/guides/features/structured-outputs)
and [routing controls](https://openrouter.ai/docs/guides/routing/provider-selection)
support `only`, `allow_fallbacks=false`, `require_parameters=true`,
`data_collection=deny`, and `zdr=true`. Every deeper request supplies all of
them. A response from another provider, missing provider identity, an unsupported
parameter, or no eligible route blocks the investigation. Catalog parameter
support does not prove current ZDR eligibility or account availability; runtime
routing must enforce it. No fallback to broader routes is permitted.

[Groq data handling](https://console.groq.com/docs/your-data) distinguishes usage
metadata from inference content. Limited reliability/abuse retention may occur
unless organization data controls opt out; there is no request-level ZDR switch.
Therefore default `data_policy=zdr_required` blocks direct Groq and the split
fails closed. `minimized_standard_retention` explicitly accepts that documented
Groq policy while still requiring ZDR at OpenRouter. Unknown policies block.
For strict ZDR requirements, obtain a verifiable Groq organization policy and
implement its enforcement before enabling this split. A local boolean would not
prove that control, so one was deliberately not added.

## Runtime, evidence and approval boundaries

SQLite migrations 021–025 and PostgreSQL 010–015 append durable jobs, results,
reviews and safe audit records. Existing cases are backfilled. Evidence events,
links, customer messages/files, commerce updates and linked financial/provider
changes increment a case evidence revision transactionally. Duplicate API
evidence replays do not write again. Many writes coalesce to the latest revision.
Shared-capture changes invalidate every owned linked resolution case.

The first authored investigation migration referred to the snapshot table
removed by commerce migration 020/009. Its SQL was retained unchanged. The
runner applies `investigation_prerequisite.sql` immediately before that migration
to create an empty transitional table; the immediate forward correction
022/011 removes it and installs the current commerce trigger, in the same
transaction. No existing numbered migration/checksum was rewritten. PostgreSQL
014 defers the new import foreign keys, and the verified importer disables only
investigation triggers during restore, flushes constraints, re-enables triggers,
and verifies copied values. This preserves stored revisions rather than
re-enqueueing restored history.

Worker claims use the existing serialized write transactions, a three-minute
lease token, revision checks and a maximum of two inference attempts per
revision. A third claim after repeated worker crashes publishes a blocked result
without inference. Late workers cannot overwrite a new revision or lease.
There are at most four HTTP attempts per worker attempt (eight over crash
recovery), at most one selected evidence refresh, one retry per provider call,
1800 default output tokens (maximum 2400), 32 KiB request and 64 KiB response
limits. HTTP timeouts default to 12 seconds (maximum 20); adapter deadlines
also bound a trickling response. Worker passes default to 20 jobs, maximum 100.
There are no model tools, arbitrary URLs, financial operations or general agents.

The allowlist is `refresh_linked_capture` / `refresh_linked_refund` with an
existing evidence-link UUID. A server callback checks ownership, link kind,
merchant/seller configuration, capture amounts and refund parent. One resource
GET plus OAuth is the maximum; a refund needs an already verified linked
capture. Automatic reads are separately disabled by default. A failed read
retains the actual earlier verified time. A read updates the evidence revision;
the old run is superseded and the next run sees the new snapshot. Attempts less
than five minutes old cannot be repeated. A single GET cannot re-establish
complete order history, so its result conservatively needs review/full history.

Findings are built by application code from existing source event/verification
IDs, decimal amounts, supported statuses, capture relationships and UTC times.
Duplicate identities, excessive refunds, future timestamps, inconsistent capture
statuses and missing history block confident conclusions. Failed refunds do not
consume completed balance; pending refunds remain pending. The manual ledger
and merchant approval claims never become provider facts. Existing acceptance,
condition, prerequisite, execution and provider-review gates remain visible as
missing evidence or contradictions. Existing independently verified payment
history is usable without a duplicate SDK refresh; its five-minute history
expiry also caps investigation freshness and invalidates advisory approval.
Model recommendations must cite existing
findings and agree with validated status/next-step enums or explicitly abstain.
Free-form model factual prose and monetary execution proposals are intentionally
not part of the accepted schema.

Notes, titles, source messages, support ticket text, conversations, attachments,
contacts, provider bodies and payment identifiers are not sent to inference.
Structured claims, facts, timestamps, source UUIDs and authorized link kinds are
sent. This reduces extraction breadth: free-text commitment extraction and
non-refund remedy investigation remain future work. Input-budget overflow,
unavailable inference, malformed/refused/truncated outputs and invalid citations
produce a private, reviewable blocked result. Raw prompts/responses never enter
operational logs; audit records contain IDs, revision/hash, model/route, bounded
usage metadata, structured assessments and validation codes.

The merchant panel appears below the selected case, with queued/running state,
the latest completed or blocked result, findings and evidence IDs, freshness,
contradictions, missing evidence, abstention/proposal, and review actions. It
polls every 15 seconds. Reviews record merchant plus a pseudonymous full-key or
session identity, timestamp, decision, revision and snapshot. Identical decisions
from that identity are idempotent; conflicting concurrent reviews have one
winner. Superseded snapshots cannot be reviewed. Expired evidence cannot be
approved; a reviewer can still reject/request evidence on the current snapshot.

`POST /resolution-cases/{case_id}/investigations/{id}/review` accepts `approve`,
`reject`, or `request_evidence`, with `expected_revision` and `evidence_snapshot`.
It always returns `authorizes_payment=false`. It never creates a refund approval,
execution, customer message or provider write. Only the pre-existing explicit
refund approval/execution routes can move money. Full merchant authentication is
required for list/review; commerce-scoped keys and buyer links cannot access
these results. Buyer payloads do not include investigation fields.

## Configuration and commands

Run these commands from `backend`. `scripts/isolated.py` clears inherited Resolve,
provider and database configuration by variable name before imports, prevents
the global FastAPI app from reading dotenv, and creates a fresh workspace-local
test database. It also avoids Python's special Windows 0700 ACL in this managed
sandbox. It never examines existing secret values.

```powershell
$env:UV_CACHE_DIR = "$PWD/../.local/uv-cache"
uv run --no-sync python scripts/isolated.py -m pytest -q -p no:cacheprovider
uv run --no-sync python scripts/isolated.py scripts/evaluate_investigations.py
uv run python scripts/isolated.py scripts/export_openapi.py
```

Direct `.venv/Scripts/python.exe` is an equivalent fallback if uv cannot access
its default cache. The exporter command requested by AGENTS is still
`uv run python scripts/export_openapi.py`; use the isolated wrapper in this run
because importing the pre-existing global app otherwise reads backend dotenv.

PostgreSQL validation used a newly initialized local cluster under
`.local/pg-ai/data`, bound only to `127.0.0.1:56439` with the synthetic
`resolve_synthetic` role. With that disposable cluster running, use
`uv run python scripts/isolated.py --postgres-local --storage-postgres -m pytest
tests/test_investigations.py tests/test_postgres.py -k "not contended_writer" -q`.
Each test creates and drops a separate schema. The excluded legacy lock-timeout
test hung in this managed host and needs rerunning with normal process signaling;
the feature concurrency and migration/import tests ran against actual local
PostgreSQL. Never point this validation at the owner's storage.
The managed host denied shutdown after this run. Stop its remaining synthetic
cluster from a normal terminal with
`& 'C:/Program Files/PostgreSQL/18/bin/pg_ctl.exe' -D 'C:/Users/navne/Desktop/paypal-resolve/.local/pg-ai/data' -m fast -w stop`.

Normal worker operation (operator-selected storage, environment injection only):

```powershell
uv run python -m app.investigation_worker             # one bounded pass
uv run python -m app.investigation_worker --loop      # every 10 seconds
```

Inference stays off unless `RESOLVE_AI_ENABLED=true`. All AI settings use the
`RESOLVE_AI_` prefix and never read dotenv. Configure `GROQ_KEY`, `OPENROUTER_KEY`,
`GROQ_MODEL`, `OPENROUTER_MODEL`, `APPROVED_GROQ_MODELS`,
`APPROVED_OPENROUTER_MODELS`, `OPENROUTER_ROUTES`, `DATA_POLICY`,
`ALLOW_SANDBOX_REFRESH`, `TIMEOUT_SECONDS`, `RETRIES`, `MAX_TOKENS` and
`FRESHNESS_SECONDS` under that prefix. Model/route tuple values use JSON arrays.
Keep credentials in the server process secret store. No browser model keys.
Storage and optional Sandbox credentials retain the existing `RESOLVE_` settings;
this worker does not load the owner's backend `.env`. It is separate from both
the refund recovery worker and hosted follow-up worker.

The TypeScript SDK adds `getInvestigations(caseId)` and
`reviewInvestigation(caseId,id,input)`. They require the direct FastAPI base URL
and a full merchant credential; the commerce SDK gateway intentionally excludes
them. `npm run build` regenerates SDK types from the OpenAPI contract.

## Evaluation and release evidence

`backend/evaluation/investigations.json` sets the rubric **before comparison**:
factual accuracy >=95%, citation validity 100%, correct abstention 100%, and
recommendation quality >=90%. Correct status, real owned citations, expected
abstention and appropriate next-step enums are scored separately. Deterministic
gates require zero tenant disclosure, unauthorized action, accepted fabricated
citation or approval bypass. These gates also require the auth/concurrency pytest
suite; model scores cannot waive a failed gate.

The 13 labels cover full, partial, pending and failed refunds, approval without
confirmation, contradictions, stale/missing evidence, provider failure, forged
citations, cross-tenant access, injection and simultaneous partial/pending amounts.
The offline evaluator runs the real adapters and worker against loopback HTTP
stand-ins. Its 100% pipeline scores show conformance to those stand-ins, not model
accuracy or real provider latency. Final factual fields are server-derived.
Raw structured model assessments are recorded separately for future comparison;
independent model grounding quality is not established by pipeline accuracy.

Optional **live synthetic only**, never run during this build:

```powershell
# Inject new evaluation-only keys under these exact names in a separate terminal:
# RESOLVE_SYNTHETIC_EVAL_GROQ_KEY, RESOLVE_SYNTHETIC_EVAL_OPENROUTER_KEY
uv run python scripts/evaluate_investigations.py --live --confirm-synthetic-only
uv run python scripts/evaluate_investigations.py --live --confirm-synthetic-only --groq-model openai/gpt-oss-120b --openrouter-model openai/gpt-4.1-mini
```

This command constructs only the fixed labeled cases in a new SQLite file. It
accepts no database, customer, case, prompt or evidence input; it never imports
the configured FastAPI app or constructs PayPal. Separate eval keys are the only
keys read. Network fault/forged-output labels remain explicitly simulated even
in live reports. Reports under `.local/ai-evaluation/` record model/route,
structured assessments, latency, token usage and estimated known token cost.
Failed-call usage and platform fees may be unknown. No model benchmarking was
performed here. Run on these labels, inspect false abstentions/invalid outputs,
and pass deterministic gates before enabling any merchant inference.

Browser test: `npx playwright test -c playwright.investigations.config.ts` from
`frontend`. It starts isolated FastAPI and a Next source copy excluding dotenv
and build caches. `npm run check` checks the surface without starting it. The
native HTTP gateway test is `node --test --experimental-test-isolation=none
tests/investigations.gateway.mjs` after those isolated servers are running.
On hosts that block Node subprocesses, start FastAPI with
`../backend/.venv/Scripts/python.exe ../backend/scripts/isolated.py tests/fixture_backend.py`
from `frontend`, then `node tests/isolated-next.mjs --in-process` in a second
terminal. That fallback uses compiler worker threads in the disposable copy.
For another loopback port, pass `--port=3109` and set
`RESOLVE_AI_UI_TEST_ORIGIN=http://127.0.0.1:3109` for the gateway test.
The SDK fixture can be started from `backend` with
`.venv/Scripts/python.exe scripts/isolated.py ../sdk/typescript/test/fixture.py ../.local/sdk-ai.sqlite3 --investigations --descriptor ../.local/sdk-ai-fixture.json`;
then run `node --test --experimental-test-isolation=none test/investigations.external.mjs`
from `sdk/typescript`. Start a fresh fixture for each SDK integration run.
Browser/visual verification remains required when the host permits launching
Playwright. Postman CLI was not available on PATH in this run; the local Python
HTTP stand-ins avoid account setup, proxy passthrough and live provider calls.
Existing Postman financial mocks/contexts were preserved. No deployment,
hosted storage, real inference, real Sandbox request or financial write was used.
