const http = require('http');
const visits = new Map();

function json(res, status, value) {
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(value));
}

http.createServer((req, res) => {
  const match = req.url.match(/^\/v2\/trackers\/(trk_([A-Z0-9]+))$/);
  if (req.method !== 'GET' || !match) return json(res, 501, { error: 'Endpoint not modeled' });
  const expected = 'Basic ' + Buffer.from('simulation-easypost-key:').toString('base64');
  if (req.headers.authorization !== expected) return json(res, 401, { error: 'Fixture key rejected' });
  const [, id, label] = match;
  if (label === 'OUTAGE') return json(res, 503, { error: 'PRIVATE-UPSTREAM-ERROR' });
  const visitsSoFar = (visits.get(id) || 0) + 1;
  visits.set(id, visitsSoFar);
  const status = label.startsWith('MOVE') ? ['pre_transit', 'in_transit', 'delivered'][Math.min(2, visitsSoFar - 1)] : 'delivered';
  return json(res, 200, { id, tracking_code: 'TEST' + label, carrier: 'UPS', status, mode: 'test' });
}).listen(process.env.PORT);
