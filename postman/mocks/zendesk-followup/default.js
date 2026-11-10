const http = require('http');
let reads = 0;

function json(res, code, body) {
  res.writeHead(code, {'Content-Type': 'application/json'});
  res.end(JSON.stringify(body));
}

http.createServer((req, res) => {
  if (req.headers.authorization !== 'Bearer simulation-zendesk-oauth') return json(res, 401, {error: 'Unauthorized'});
  const url = new URL(req.url, 'https://resolve-helpdesk.zendesk.com');
  if (req.method === 'GET' && url.pathname === '/api/v2/users/me.json') return json(res, 200, {user: {id: 7, role: 'agent'}});
  if (req.method === 'GET' && url.pathname === '/api/v2/users/show_many.json') return json(res, 200, {users: [{id: 7, role: 'agent'}, {id: 8, role: 'end-user'}]});
  if (req.method === 'GET' && url.pathname === '/api/v2/tickets/123/comments.json') {
    const second = url.searchParams.get('page') === '2';
    return json(res, 200, {comments: second
      ? [{id: 92, author_id: 8, plain_body: 'My synthetic item is damaged.', public: true, created_at: '2026-11-09T09:00:00Z'}]
      : [{id: 91, author_id: 7, plain_body: 'We will refund $25 after the return.', public: false, created_at: '2026-11-09T10:00:00Z'}],
      next_page: second ? null : 'https://resolve-helpdesk.zendesk.com/api/v2/tickets/123/comments.json?page=2'});
  }
  const ticket = url.pathname.match(/^\/api\/v2\/tickets\/([0-9]+)(?:\.json)?$/);
  if (req.method !== 'GET' || !ticket) return json(res, 501, {error: 'Endpoint not modeled'});
  if (ticket[1] !== '123') return json(res, 404, {error: 'RecordNotFound'});
  reads += 1;
  return json(res, 200, {ticket: {id: 123, external_id: 'ORDER-TEST', subject: 'Synthetic refund request', status: reads === 1 ? 'open' : 'pending', description: 'PRIVATE ZENDESK BODY'}});
}).listen(process.env.PORT);
