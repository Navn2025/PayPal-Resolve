# Resolve merchant UI plan

Build the hackathon UI in the existing repository as a local Next.js application.
The primary task is to open a support case, understand the promise and its
evidence, and take the next safe action. The UI must work without account setup
in a clearly labeled demo, and must also connect to the existing local API.

1. Build the merchant inbox: searchable cases, status filters, a review queue,
   and a case creation dialog. Use a navy navigation rail and a light workspace,
   with the most important amounts and status visible at a glance.
2. Build the case desk: promise and evidence cards, provider refresh and
   revision forms, the audit timeline, and a printable buyer receipt. A $30
   promise with $10 already returned is the default demo. Use an exact amount
   approval followed by a separate submit action.
3. Connect the local backend: validate the merchant token on the server, keep it
   out of browser storage, and use existing FastAPI routes. Re-read the current
   reconciliation before approval, and let the backend enforce stale approvals
   and payment state. Keep the simulated external refund scenario in demo mode.
4. Check the complete demo, exception, and connected flows on desktop and mobile.
   Document local startup and update the engineering log. Leave the app local
   and the working tree uncommitted.

Use React, TypeScript and local design tokens. Browser login with individual
roles, public receipt links, external deployment, and live financial actions
are outside this UI phase.
