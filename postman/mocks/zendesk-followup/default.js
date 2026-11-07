const http = require('http');
let reads = 0;

function json(res, code, body) {
  res.writeHead(code, {'Content-Type': 'application/json'});
  res.end(JSON.stringify(body));
}

http.createServer((req, res) => {
  if (req.headers.authorization !== 'Bearer simulation-zendesk-oauth') return json(res, 401, {error: 'Unauthorized'});
  const ticket = req.url.match(/^\/api\/v2\/tickets\/([0-9]+)$/);
  if (req.method !== 'GET' || !ticket) return json(res, 501, {error: 'Endpoint not modeled'});
  if (ticket[1] !== '123') return json(res, 404, {error: 'RecordNotFound'});
  reads += 1;
  return json(res, 200, {ticket: {id: 123, status: reads === 1 ? 'open' : 'pending', description: 'PRIVATE ZENDESK BODY'}});
}).listen(process.env.PORT);
