const http = require('http');
const attempts = new Map();
const accepted = new Map();

function json(res, code, body) {
  res.writeHead(code, {'Content-Type': 'application/json'});
  res.end(JSON.stringify(body));
}

http.createServer((req, res) => {
  if (req.headers.authorization !== 'Bearer simulation-resend-token') return json(res, 401, {message: 'Invalid test authorization'});
  if (req.method === 'GET' && req.url === '/__test/messages') return json(res, 200, {accepted: [...accepted.values()], attempts: [...attempts]});
  if (req.method !== 'POST' || req.url !== '/emails') return json(res, 501, {message: 'Endpoint not modeled'});
  const key = req.headers['idempotency-key'];
  const body = req.body;
  if (!/^resolve\/[a-f0-9-]{36}$/.test(key || '') || body?.from !== 'updates@example.com' ||
      !Array.isArray(body.to) || body.to.length !== 1 || !body.subject || !body.text) {
    return json(res, 422, {message: 'Expected a transactional email with an idempotency key'});
  }
  const count = (attempts.get(key) || 0) + 1;
  attempts.set(key, count);
  if (body.to[0] === 'retry@example.com' && count === 1) return json(res, 429, {message: 'Test rate limit'});
  if (!accepted.has(key)) accepted.set(key, {key, body, id: 'simulated-email-' + accepted.size});
  return json(res, 200, {id: accepted.get(key).id});
}).listen(process.env.PORT);
