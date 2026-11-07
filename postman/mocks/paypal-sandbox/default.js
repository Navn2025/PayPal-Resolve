const http = require('http');
const crypto = require('crypto');
const TOKEN = 'simulation-access-token';
const refundsByRequest = new Map();
const refundsById = new Map();
const captureStats = new Map();
function stats(id) {
  if (!captureStats.has(id)) captureStats.set(id, { refund_posts: 0, refund_creations: 0, request_ids: [], refund_ids: [] });
  return captureStats.get(id);
}
function json(res, status, value) {
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(value));
}
const money = (cents) => ({ value: (cents / 100).toFixed(2), currency_code: 'USD' });
const captureRefunds = (capture) => [...refundsById.values()]
  .filter(record => record.capture === capture).map(record => record.refund);
const used = (capture, statuses) => captureRefunds(capture)
  .filter(refund => statuses.includes(refund.status))
  .reduce((cents, refund) => cents + Math.round(Number(refund.amount.value) * 100), 0);
function captureDetails(id) {
  const completed = used(id, ['COMPLETED']);
  return {
    id, status: completed === 10000 ? 'REFUNDED' : completed > 0 ? 'PARTIALLY_REFUNDED' : 'COMPLETED',
    amount: money(10000), payee: { merchant_id: 'SIMSELLER001' }
  };
}
function newRefund(capture, id, cents, status, customId) {
  return {
    id, amount: money(cents), status,
    ...(customId ? { custom_id: customId } : {}),
    seller_payable_breakdown: {
      total_refunded_amount: money(used(capture, ['COMPLETED']) + (status === 'COMPLETED' ? cents : 0))
    },
    links: [
      { rel: 'self', method: 'GET', href: 'https://api-m.sandbox.paypal.com/v2/payments/refunds/' + id },
      { rel: 'up', method: 'GET', href: 'https://api-m.sandbox.paypal.com/v2/payments/captures/' + capture }
    ]
  };
}
http.createServer((req, res) => {
  const path = new URL(req.url, 'http://localhost').pathname;
  if (req.method === 'POST' && path === '/v1/oauth2/token') {
    const basic = req.headers.authorization || '';
    const decoded = Buffer.from(basic.replace(/^Basic /, ''), 'base64').toString('utf8');
    const colon = decoded.indexOf(':');
    const client = decoded.slice(0, colon);
    const secret = decoded.slice(colon + 1);
    let body = req.body || {};
    if (typeof body === 'string' || Buffer.isBuffer(body)) {
      body = Object.fromEntries(new URLSearchParams(body.toString()));
    }
    if (body.grant_type === 'authorization_code') {
      if (client !== 'simulation-login-client' || secret !== 'simulation-login-secret') return json(res, 401, { error: 'invalid_client' });
      if (!/^https?:\/\/(resolve\.example\.com|127\.0\.0\.1:3100)\/api\/auth\/paypal\/callback$/.test(body.redirect_uri || '')) {
        return json(res, 400, { error: 'invalid_redirect_uri' });
      }
      if (body.code === 'resolve-code-outage') return json(res, 503, { error: 'PRIVATE-PROVIDER-ERROR' });
      if (!/^resolve-code-(merchant|other|missing)$/.test(body.code || '')) return json(res, 400, { error: 'invalid_grant' });
      return json(res, 200, { access_token: 'identity-' + body.code, token_type: 'Bearer', refresh_token: 'DO-NOT-STORE' });
    }
    if (!basic.startsWith('Basic ') || secret !== 'simulation-secret' || client === 'bad-client') {
      return json(res, 401, { error: 'invalid_client', secret: 'DO-NOT-LEAK-UPSTREAM-BODY' });
    }
    if (body.grant_type !== 'client_credentials') return json(res, 400, { error: 'bad_grant' });
    if (client === 'malformed-token') return json(res, 200, { access_token: '', token_type: 'Bearer', expires_in: 300 });
    return json(res, 200, { access_token: TOKEN, token_type: 'Bearer', expires_in: 300 });
  }
  if (req.method === 'GET' && path === '/v1/identity/openidconnect/userinfo') {
    const identity = /^Bearer identity-resolve-code-(merchant|other|missing)$/.exec(req.headers.authorization || '');
    if (!identity || new URL(req.url, 'http://localhost').searchParams.get('schema') !== 'openid') {
      return json(res, 401, { error: 'Token rejected' });
    }
    return json(res, 200, identity[1] === 'missing' ? { email: 'buyer@example.com' }
      : { sub: 'simulation-subject-' + identity[1], email: 'same-address@example.com', email_verified: true });
  }
  if (req.headers.authorization !== 'Bearer ' + TOKEN) return json(res, 401, { error: 'Token rejected' });
  const authorization = path.match(/^\/v2\/payments\/authorizations\/(SIMAUTH[A-Z0-9]+)$/);
  if (req.method === 'GET' && authorization) return json(res, 200, {
    id: authorization[1], status: authorization[1].endsWith('CAPTURED') ? 'CAPTURED' : 'VOIDED'
  });
  const subscription = path.match(/^\/v1\/billing\/subscriptions\/(I-SIM[A-Z0-9]+)$/);
  if (req.method === 'GET' && subscription) return json(res, 200, {
    id: subscription[1], status: subscription[1].endsWith('PAUSE') ? 'SUSPENDED' : 'CANCELLED'
  });
  const invoice = path.match(/^\/v2\/invoicing\/invoices\/(INV2-SIM[A-Z0-9]+)$/);
  if (req.method === 'GET' && invoice) return json(res, 200, {
    id: invoice[1], status: invoice[1].endsWith('OFFLINE') ? 'MARKED_AS_REFUNDED' : 'CANCELLED'
  });
  const dispute = path.match(/^\/v1\/customer\/disputes\/(PP-D-([A-Z0-9]+))$/);
  if (req.method === 'GET' && dispute) return json(res, 200, {
    dispute_id: dispute[1], status: 'WAITING_FOR_SELLER_RESPONSE',
    disputed_transactions: [{ seller_transaction_id: dispute[2], seller: { merchant_id: 'SIMSELLER001' }}],
    seller_response_due_date: '2027-01-01T12:00:00Z',
    messages: [{ content: 'UNNEEDED-BUYER-DATA' }]
  });
  // Test-harness observability only; the application never calls this route.
  const inspect = path.match(/^\/__resolve_test\/state\/([A-Za-z0-9]+)$/);
  if (req.method === 'GET' && inspect) return json(res, 200, stats(inspect[1]));
  if (req.method === 'POST' && path === '/v1/notifications/verify-webhook-signature') {
    const body = req.body || {};
    if (body.transmission_sig === 'dW5hdmFpbGFibGU=') return json(res, 503, { error: 'Temporarily unavailable' });
    return json(res, 200, {
      verification_status: body.webhook_id === 'SIMWEBHOOK001' &&
        body.transmission_sig === 'c2lnbmVk' && body.webhook_event?.id ? 'SUCCESS' : 'FAILURE'
    });
  }
  const orderGet = path.match(/^\/v2\/checkout\/orders\/SIMORDER(SIMH[A-Za-z0-9]+)$/);
  if (req.method === 'GET' && orderGet) {
    const capture = orderGet[1];
    const details = captureDetails(capture);
    const all = captureRefunds(capture);
    const refunds = capture.includes('HIDDEN') ? all.slice(1) : all;
    return json(res, 200, {
      id: 'SIMORDER' + capture, status: 'COMPLETED',
      purchase_units: [{ payee: details.payee, payments: { captures: [details], refunds } }]
    });
  }
  const external = path.match(/^\/__resolve_test\/external\/(SIMH[A-Za-z0-9]+)$/);
  if (req.method === 'POST' && external) {
    const capture = external[1];
    const body = req.body || {};
    const id = 'SIMEXT' + crypto.randomBytes(8).toString('hex').toUpperCase();
    const refund = newRefund(capture, id, body.cents, body.status || 'COMPLETED');
    refundsById.set(id, { capture, refund });
    return json(res, 201, refund);
  }
  const refundPost = path.match(/^\/v2\/payments\/captures\/([A-Za-z0-9]+)\/refund$/);
  if (req.method === 'POST' && refundPost) {
    const capture = refundPost[1];
    const key = req.headers['paypal-request-id'];
    const count = stats(capture);
    count.refund_posts++;
    count.request_ids.push(key || 'MISSING');
    if (!key || !/^[0-9a-f-]{36}$/i.test(key)) return json(res, 400, { error: 'Request identity required' });
    let body = req.body || {};
    if (typeof body === 'string' || Buffer.isBuffer(body)) {
      try { body = JSON.parse(body.toString()); } catch { return json(res, 400, { error: 'Bad JSON' }); }
    }
    const history = capture.startsWith('SIMH');
    if (!body.amount || !/^\d+\.\d{2}$/.test(body.amount.value) || body.amount.currency_code !== 'USD' ||
        (history ? body.custom_id !== 'resolve-' + key : body.amount.value !== '100.00')) {
      return json(res, 422, { error: 'Explicit amount and matching request identity required' });
    }
    const cents = Math.round(Number(body.amount.value) * 100);
    if (req.headers.prefer !== 'return=representation') return json(res, 400, { error: 'Representation required' });
    const previous = refundsByRequest.get(key);
    if (previous) {
      if (previous.capture !== capture || previous.body !== JSON.stringify(body)) return json(res, 422, { error: 'Request identity reused with different data' });
      return json(res, 200, previous.refund);
    }
    if (capture.includes('REJECT')) return json(res, 422, { error: 'DO-NOT-LEAK-UPSTREAM-BODY' });
    if ((!history && count.refund_creations) || cents < 1 || cents + used(capture, ['COMPLETED','PENDING']) > 10000) {
      return json(res, 422, { error: 'Capture already reserved/refunded' });
    }
    const id = 'SIMREF' + crypto.createHash('sha256').update(key).digest('hex').slice(0, 18).toUpperCase();
    const refund = newRefund(capture, id, cents,
      capture.includes('PENDING') ? 'PENDING' : capture.includes('FAILREFUND') ? 'FAILED' : 'COMPLETED',
      body.custom_id);
    const record = { capture, body: JSON.stringify(body), refund };
    refundsByRequest.set(key, record);
    refundsById.set(id, record);
    count.refund_creations++;
    count.refund_ids.push(id);
    if (capture.includes('TIMEOUT')) return setTimeout(() => json(res, 201, refund), 1500);
    if (capture.includes('BADJSON')) {
      res.writeHead(201, { 'Content-Type': 'text/html' });
      return res.end('<html>DO-NOT-LEAK-UPSTREAM-BODY</html>');
    }
    const output = JSON.parse(JSON.stringify(refund));
    if (capture.includes('BADAMOUNT')) output.amount.value = '90.00';
    if (capture.includes('BADPARENT') && !capture.includes('READBADPARENT')) output.links = [];
    return json(res, 201, output);
  }
  const refundGet = path.match(/^\/v2\/payments\/refunds\/([A-Za-z0-9]+)$/);
  if (req.method === 'GET' && refundGet) {
    const record = refundsById.get(refundGet[1]);
    if (!record) return json(res, 404, { error: 'Unknown refund' });
    const output = JSON.parse(JSON.stringify(record.refund));
    if (record.capture.includes('READBADPARENT')) output.links[1].href = 'https://api-m.sandbox.paypal.com/v2/payments/captures/WRONGCAPTURE';
    else if (record.capture.includes('READNOUP')) output.links = [];
    else if (record.capture.includes('READBADURL')) output.links[1].href = 'https://[';
    else if (output.status === 'PENDING' && !record.capture.startsWith('SIMH')) {
      record.refund.status = 'COMPLETED';
      output.status = 'COMPLETED';
    }
    return json(res, 200, output);
  }
  const match = path.match(/^\/v2\/payments\/captures\/([A-Za-z0-9]+)$/);
  if (req.method !== 'GET' || !match) return json(res, 501, { error: 'Endpoint not modeled' });
  const id = match[1];
  if (id === 'SIMCAPTURE404') return json(res, 404, { error: 'RESOURCE_NOT_FOUND' });
  if (id === 'SIMCAPTURE403') return json(res, 403, { error: 'DO-NOT-LEAK-UPSTREAM-BODY' });
  if (id === 'SIMCAPTURE429') return json(res, 429, { error: 'Rate limited' });
  if (id === 'SIMCAPTURE503') return json(res, 503, { error: 'Unavailable' });
  if (id === 'SIMCAPTUREJSON') {
    res.writeHead(200, { 'Content-Type': 'text/html' });
    return res.end('<html>DO-NOT-LEAK-UPSTREAM-BODY</html>');
  }
  if (id === 'SIMCAPTUREREDIRECT') {
    res.writeHead(302, { Location: 'https://example.invalid/do-not-follow' });
    return res.end();
  }
  const data = captureDetails(id);
  if (id === 'SIMCAPTUREAMOUNT') data.amount.value = '90.00';
  if (id === 'SIMCAPTUREPAYEE') data.payee.merchant_id = 'OTHERSELLER';
  if (id === 'SIMCAPTURENOPAYEE') delete data.payee;
  if (id === 'SIMCAPTUREID') data.id = 'WRONGCAPTURE';
  if (id === 'SIMCAPTUREFLOAT') data.amount.value = 100.00;
  if (id === 'SIMCAPTURENAN') data.amount.value = 'NaN';
  if (id === 'SIMCAPTUREEUR') data.amount.currency_code = 'EUR';
  if (id === 'SIMCAPTURESTATUS') data.status = 'UNKNOWN_STATUS';
  if (id === 'SIMCAPTUREPENDING') data.status = 'PENDING';
  if (id === 'SIMCAPTUREREFUNDED') data.status = 'REFUNDED';
  if (id === 'SIMCAPTURETIMEOUT') return setTimeout(() => json(res, 200, data), 1500);
  return json(res, 200, data);
}).listen(process.env.PORT);
