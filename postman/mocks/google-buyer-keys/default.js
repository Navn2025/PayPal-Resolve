const http = require('http');
const keys = new Map();
function json(res, status, body) {
  res.writeHead(status, {'Content-Type': 'application/json'});
  res.end(JSON.stringify(body));
}
http.createServer((req, res) => {
  if (req.method === 'POST' && req.url === '/__resolve_fixture/jwk' && req.body?.kid) {
    keys.set(req.body.kid, req.body);
    return json(res, 201, {registered: true});
  }
  if (req.method === 'GET' && req.url === '/oauth2/v3/certs') return json(res, 200, {keys: [...keys.values()]});
  return json(res, 501, {error: 'unmodeled'});
}).listen(process.env.PORT);
