# Resolve merchant UI

The Next.js app opens with a public landing page. The separate demo has a merchant
inbox, case detail, promises and evidence, a review queue, and a buyer receipt
that can be printed or saved as a PDF. A separate
[customer portal](http://127.0.0.1:3000/customer?demo=1) opens directly.

From this directory:

```powershell
npm ci
npm run dev
```

Open <http://127.0.0.1:3000> and choose **Explore the demo**. The demo at
`/demo` needs no credentials or backend.
To try the duplicate-refund branch, approve the sample refund and choose
**Simulate outside refund** beside the submission action. Use **Reset demo**
to try the normal submission path again. Demo changes are kept in memory.

To work with actual local case records:

1. In a separate terminal, run `uv run uvicorn app.main:app --reload` from
   `backend`.
2. Select **Merchant sign in** and enter an existing private Resolve merchant
   key. If you need a key, use the [backend account setup](../backend/README.md).
3. Select **New case** to create a standalone case, link an existing refund
   case, or record a PayPal payment. Record the promise in the case. A linked
   refund promise must match the accepted commitment on its payment case.
4. Check provider evidence, then review an exact refund amount. Approval and
   submission are separate. Connected refund submissions use the existing
   opt-in PayPal Sandbox path.

If the backend uses another port or service, copy `.env.example` to
`.env.local` and set `RESOLVE_BACKEND_URL`. The browser gets an opaque
HttpOnly token for a durable backend session; it never receives the access
key back. See [merchant sign-in](../docs/MERCHANT_SIGN_IN.md) for PayPal
linking and production start commands.

To share a case, open **Customer portal** in the case desk, choose a heading,
and create the link. Customers see progress and can exchange messages without
a merchant key. Links expire after seven days and can be replaced or revoked.
For links that work outside this machine, configure an HTTPS public origin.
See the [customer portal guide](../docs/CUSTOMER_PORTAL.md).

To let a buyer start a new case, choose **Invite customer** and enter the order
reference. The link opens the intake form, then the case timeline, evidence
uploads, and conversation. Choose **Manage case** to set assignment, due date,
and whether the case is waiting on the buyer. The inbox can filter by workflow
or unread messages; **Customer portal** contains the buyer's files and replies.
See [the full walkthrough](../docs/CUSTOMER_WORKFLOW.md) or open the
[sample intake](http://127.0.0.1:3000/customer?intake=1).

The optional [hosted follow-up setup](../docs/HOSTED_FOLLOWUP.md) enables email
invites, the **My cases** email sign-in screen, and an optional merchant
Zendesk card. Copyable invites still work in the local demo without email.

`npm run check` checks TypeScript; `npm run build` builds production
assets. To run browser tests, install Playwright's Chromium with
`npx playwright install chromium`, or set
`PLAYWRIGHT_CHROMIUM_EXECUTABLE` to your local Chrome executable, then run
`npm run test:e2e`. These tests use ports 3100 and 8011, temporary SQLite,
and a synthetic merchant. They do not use the configured development database.

To include the payment and PayPal login browser tests, run
from the repository root:

```powershell
$env:RESOLVE_UI_PAYPAL_SIMULATION = '1'
$env:RESOLVE_UI_PAYPAL_LOGIN = '1'
$env:RESOLVE_UI_EMAIL_FIXTURE = '1'
postman simulation run postman/simulations/paypal-read/paypal-read.sim.yaml --proxy --lift "npm --prefix frontend run test:e2e" --output ndjson
```

The simulated provider tests use fake credentials. The Playwright readiness
checks for local services bypass the provider proxy. For product and implementation
scope, see the [frontend plan](../docs/FRONTEND_PLAN.md) and
[engineering log](../docs/ENGINEERING_LOG.md).
