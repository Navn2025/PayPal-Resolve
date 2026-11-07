# Resolve landing page and merchant sign-in

| Route | What it opens |
| --- | --- |
| `/` | Public landing page with merchant, buyer, and demo entry points |
| `/demo` | Isolated workspace using sample records |
| `/login` | Merchant sign-in with a Resolve access key or linked PayPal account |
| `/workspace` | Signed-in merchant inbox |
| `/workspace/settings` | Link or unlink PayPal, review session details, and sign out |
| `/customer`, `/customer/account` | Private buyer link and separate My cases sign-in |

An administrator creates or issues a merchant access key through
`app.manage`. Use that key at `/login` the first time. A successful sign-in
sets an HttpOnly browser session; the API stores only a hash of the session
token. A session lasts eight hours. Sign-out revokes it, and revoking an
access key also invalidates sessions issued using that key. Existing
integrations can continue using their provisioned API bearer keys.

## Enable Log in with PayPal

1. In the [PayPal Developer Dashboard](https://developer.paypal.com/log-in/build),
   open the chosen Sandbox REST app and enable **Log in with PayPal**. Add the
   exact return URL `https://YOUR-RESOLVE-HOST/api/auth/paypal/callback`.
   Use the same origin when opening Resolve and when configuring the app. PayPal
   also asks for Privacy Policy and User Agreement URLs. Its docs permit example
   URLs for Sandbox testing; use your real published policies for live review.
2. Set these variables on the **backend**:

   ```dotenv
   RESOLVE_MERCHANT_WEB_ORIGIN=https://YOUR-RESOLVE-HOST
   RESOLVE_PAYPAL_LOGIN_ENABLED=true
   RESOLVE_PAYPAL_LOGIN_ENVIRONMENT=sandbox
   RESOLVE_PAYPAL_LOGIN_CLIENT_ID=YOUR_SANDBOX_LOGIN_APP_CLIENT_ID
   RESOLVE_PAYPAL_LOGIN_CLIENT_SECRET=YOUR_SANDBOX_LOGIN_APP_CLIENT_SECRET
   ```

   Set `RESOLVE_MERCHANT_WEB_ORIGIN` to that same origin on the **frontend**.
   Set `RESOLVE_CUSTOMER_PUBLIC_ORIGIN` on both if the buyer portal has a
   different host or if you enable [customer email](HOSTED_FOLLOWUP.md).
   Keep login credentials and the database URL on the backend. Refund API
   settings use separate variables and are unaffected.
3. Sign in with the merchant access key, open **Settings → Link PayPal**, and
   complete PayPal consent in the same browser. After that, sign out and use
   **Log in with PayPal**. Linking or unlinking requires a key session created
   in the last 30 minutes; unlinking revokes active PayPal sessions for that
   workspace.

Resolve requests the `openid` identity scope. It does not store PayPal
access tokens or refresh tokens and does not match accounts by email. The
PayPal account can open only the Resolve workspace to which it was
explicitly linked. A browser session cannot enable refund writes or replace
PayPal's separate [seller permissions](https://developer.paypal.com/platforms/seller-onboarding/onboarding-checklist/).
PayPal requires [review for live Log in with PayPal](https://developer.paypal.com/log-in/build#go-live);
do not switch to the live environment until the app and exact return URL are
approved and tested.

## Deployment notes

- For a directly exposed Next.js service, build it and run
  `npm run start:hosted`. The regular `npm start` binds to loopback for a
  reverse proxy on the same host.
- Set frontend `RESOLVE_BACKEND_URL` to the FastAPI origin. Plain HTTP is
  allowed on loopback; use HTTPS for an external host, or set
  `RESOLVE_BACKEND_ALLOW_PRIVATE_HTTP=true` only on a trusted private network.
  Preserve the external `Host` header when proxying browser routes.
- Use FastAPI `GET /health` as a deployment liveness check. The original
  POST endpoint still works. Backend startup applies pending migrations
  (currently through SQLite 018 or PostgreSQL 007).
- Restrict public backend ingress to the existing PayPal webhook and
  appropriate health routes if the frontend can reach FastAPI privately.
  Configure access logs to omit query strings on the PayPal callback.
- The repository verifies OAuth against a local HTTPS simulation. Register
  and test an actual PayPal app and HTTPS callback before relying on it for
  a deployment.
