const http = require('http');
const crypto = require('crypto');
const grants = new Map();
function json(res, status, body) {
  res.writeHead(status, {'Content-Type': 'application/json'});
  res.end(JSON.stringify(body));
}
http.createServer((req, res) => {
  if (req.method !== 'POST') return json(res, 501, {error: 'unmodeled'});
  if (req.url === '/__resolve_fixture/authorize') {
    const {code, id_token, challenge, redirect} = req.body || {};
    if (![code, id_token, challenge, redirect].every(v => typeof v === 'string')) return json(res, 400, {error: 'bad_fixture'});
    grants.set(code, {id_token, challenge, redirect});
    return json(res, 201, {registered: true});
  }
  if (req.url !== '/token') return json(res, 501, {error: 'unmodeled'});
  let body = req.body || {};
  if (typeof body === 'string' || Buffer.isBuffer(body)) body = Object.fromEntries(new URLSearchParams(body.toString()));
  if (body.client_id !== 'simulation-google-client' || body.client_secret !== 'simulation-google-secret') {
    return json(res, 401, {error: 'invalid_client'});
  }
  const grant = grants.get(body.code);
  const challenge = crypto.createHash('sha256').update(body.code_verifier || '').digest('base64url');
  if (!grant || grant.challenge !== challenge || grant.redirect !== body.redirect_uri || body.grant_type !== 'authorization_code') {
    return json(res, 400, {error: 'invalid_grant'});
  }
  grants.delete(body.code);
  return json(res, 200, {id_token: grant.id_token, access_token: 'synthetic-not-used', token_type: 'Bearer'});
}).listen(process.env.PORT);
