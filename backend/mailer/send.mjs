import { readFileSync } from "node:fs";
import nodemailer from "nodemailer";

let status = "failed";
let transport;
try {
  const { host, port, secure, user, password, message } = JSON.parse(readFileSync(0, "utf8"));
  transport = nodemailer.createTransport({
    host,
    port,
    secure,
    requireTLS: !secure,
    auth: { user, pass: password },
    tls: { minVersion: "TLSv1.2" },
    connectionTimeout: 8_000,
    greetingTimeout: 8_000,
    socketTimeout: 10_000,
    disableFileAccess: true,
    disableUrlAccess: true,
  });
  const result = await transport.sendMail(message);
  if (result.accepted.length === 1 && !result.rejected.length) status = "accepted";
} catch (error) {
  // An explicit transient SMTP rejection is safe to retry; an interrupted
  // transfer may already have been accepted and is never retried automatically.
  if (Number.isInteger(error?.responseCode) && error.responseCode >= 400 &&
      error.responseCode < 500) status = "retry";
} finally {
  transport?.close();
}
process.stdout.write(JSON.stringify({ status }));
