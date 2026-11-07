# Buyer sign-in and email

Buyers can open their private case link without an account. To return later,
they can use **My cases** at `/customer/account` with Google or a one-time
email link. Neither option grants access to the merchant workspace.

## Enable Google for My cases

1. In [Google Auth Platform](https://console.cloud.google.com/auth/clients),
   create a **Web application** OAuth client. Set the consent screen and add
   a test user if the project's audience is restricted. Register
   `https://YOUR-FRONTEND-HOST/api/customer-account/google/callback` as an
   **authorized redirect URI**. Use your actual buyer frontend URL.
2. Add these values to the FastAPI environment:

   ```dotenv
   RESOLVE_CUSTOMER_PUBLIC_ORIGIN=https://YOUR-FRONTEND-HOST
   RESOLVE_CUSTOMER_GOOGLE_ENABLED=true
   RESOLVE_GOOGLE_CLIENT_ID=YOUR_WEB_APPLICATION_CLIENT_ID
   RESOLVE_GOOGLE_CLIENT_SECRET=YOUR_WEB_APPLICATION_CLIENT_SECRET
   ```

   Set the same `RESOLVE_CUSTOMER_PUBLIC_ORIGIN` in the frontend environment;
   credentials stay on the backend. For Google-only local testing, use the
   loopback origin registered with the exact callback. Email delivery still
   requires a public HTTPS origin.
3. Restart both apps. From the merchant inbox, create an order invite using
   the buyer email already verified for that order. Leave **Email this invite
   from Resolve** unchecked if you are sharing the link yourself. After the
   buyer submits the issue, they can choose **Sign in with Google** using the
   same email and open their case. This works with email delivery disabled.

Resolve verifies Google's signed ID token and uses the matching email to
find already assigned cases. Verified Gmail and Google Workspace addresses
with a matching hosted domain are supported. For other addresses, use the
private case link or verify the mailbox with the email sign-in option. See
[Google's web OAuth setup](https://developers.google.com/identity/protocols/oauth2/web-server)
and [ID token guidance](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token).
Configure hosted request logs to omit OAuth callback query strings. The
buyer button uses a [Google-provided brand asset](https://developers.google.com/identity/branding-guidelines).

## Enable buyer email

Use **Resend** for the simplest FastAPI deployment. It sends through the
existing Python follow-up worker with no Node mail runtime. Set
`RESOLVE_CUSTOMER_EMAIL_TRANSPORT=resend` (the default) and follow the
[hosted follow-up setup](HOSTED_FOLLOWUP.md) for the sender, API key, and worker.

Choose SMTP only if you already have a relay or prefer to use one. The
existing follow-up worker invokes a small Nodemailer script for each email;
there is no separate HTTP service or queue to deploy. Install Node.js and run
`npm --prefix backend/mailer ci --omit=dev` on the machine running the worker.
Then set these backend and worker variables:

```dotenv
RESOLVE_CUSTOMER_EMAIL_ENABLED=true
RESOLVE_CUSTOMER_EMAIL_TRANSPORT=smtp
RESOLVE_CUSTOMER_EMAIL_MERCHANT_ID=YOUR_RESOLVE_MERCHANT_UUID
RESOLVE_CUSTOMER_PUBLIC_ORIGIN=https://YOUR-FRONTEND-HOST
RESOLVE_CUSTOMER_SIGNING_KEY=YOUR_STABLE_RANDOM_SECRET
RESOLVE_SMTP_HOST=smtp.example.com
RESOLVE_SMTP_PORT=587
RESOLVE_SMTP_SECURE=false
RESOLVE_SMTP_USER=YOUR_SMTP_USERNAME
RESOLVE_SMTP_PASSWORD=YOUR_SMTP_PASSWORD
RESOLVE_SMTP_FROM=updates@example.com
```

Port 587 with `RESOLVE_SMTP_SECURE=false` requires STARTTLS. For a provider
using implicit TLS, usually on port 465, set `RESOLVE_SMTP_SECURE=true`.
Use an authorized sender address for the chosen SMTP account.
[Nodemailer SMTP reference](https://nodemailer.com/smtp)

Run `uv run python -m app.followup_worker --loop` from `backend` with the
same PostgreSQL connection and email settings as the API. Test with your own
address first. If you are switching transports, drain existing mail jobs first:
a job with a previous attempt stays assigned to its original transport. For
SMTP, only a definite temporary rejection is retried. An interruption after
submission may mean the server accepted the message; the worker stops retrying
that job. Acceptance means the provider took the message, not that it reached
the inbox.
