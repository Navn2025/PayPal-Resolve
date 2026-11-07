# Repository working instructions

## Keep the engineering log current

The project owner requires a written account of what changed, why it changed,
and why each material implementation choice was made.

Read `docs/ENGINEERING_LOG.md` before changing this project. Every change to
application code, tests, dependencies, configuration, API contracts, database
schemas, migrations, or development scripts must include a corresponding update
to that log in the same change set, before handing work back to the user. Also
log documentation changes that materially affect setup, behavior, or decisions.

Each entry must include:

1. A unique change ID, date, and concrete objective.
2. Files changed and resulting behavior, including API or data-model changes.
3. The reason for the change and why the chosen approach fits the current stage.
4. Material alternatives considered, tradeoffs, and assumptions. Record these
   when relevant; do not invent alternatives merely to fill a template.
5. Validation actually performed: commands, results, and what those checks prove.
   State when a check was not run, and distinguish local, simulated, sandbox, and
   live evidence.
6. Remaining limitations, compatibility changes, and the next relevant step.

For a small change, a concise entry is sufficient. Explain meaningful decisions
with enough detail that another developer can understand the implementation
without reading the chat. Link existing decision IDs instead of duplicating them.

Append new entries. Preserve previous entries; identify corrections explicitly.
Update the current-state summary when behavior changes. Use `supersedes` links
when a decision changes, and retain the reason for the earlier decision.

Never invent historical dates, timestamps, commits, tests, or outcomes. Clearly
label reconstructed history as retrospective. Do not store API keys, tokens,
credentials, private customer information, or raw production evidence in the log.

## Keep claims aligned with implementation

Keep `README.md` and `backend/README.md` accurate when behavior or setup changes.
Distinguish planned features from implemented features. Manual development
records and recommendations are not verified PayPal outcomes or authorization
to move money.

When changing reconciliation, validate amount precision, duplicate handling,
pending/failed refund behavior, shared capture balances, and the relevant
acceptance/condition gates. Run the appropriate tests and record the outcome.

The engineering log records development decisions. It does not replace runtime
audit events, source evidence, database migrations, or Git history. Do not commit
or push changes unless authorized by the user.

## Keep the API contract reusable

After API/model changes, regenerate `postman/contracts/resolve.openapi.json` from
the backend directory with `uv run python scripts/export_openapi.py`. The file is
generated from FastAPI's contract; do not put local credentials or customer data
in examples. Update the relevant local simulation/context when provider behavior
changes, and distinguish local, simulated and account-backed validation in the log.
