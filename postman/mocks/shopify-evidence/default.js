const http = require('http');

function json(res, status, value) {
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(value));
}

http.createServer((req, res) => {
  if (req.method !== 'POST' || req.url !== '/admin/api/2026-10/graphql.json') {
    return json(res, 501, { error: 'Endpoint not modeled' });
  }
  if (req.headers['x-shopify-access-token'] !== 'simulation-shopify-token') {
    return json(res, 401, { error: 'Fixture token rejected' });
  }
  const { query, variables } = req.body || {};
  const id = variables?.id;
  if (typeof query !== 'string' || !query.startsWith('query ') || !id) {
    return json(res, 400, { error: 'GraphQL query and ID required' });
  }
  let node = null;
  if (query.includes('on Order') && id === 'gid://shopify/Order/101') {
    node = { id, cancelledAt: '2026-11-07T10:00:00Z' };
  } else if (query.includes('on Order') && id === 'gid://shopify/Order/102') {
    node = { id, cancelledAt: null };
  } else if (query.includes('on StoreCreditAccountCreditTransaction') && id === 'gid://shopify/StoreCreditAccountCreditTransaction/301') {
    node = { id, account: { id: 'gid://shopify/StoreCreditAccount/201' }, amount: { amount: '15.00', currencyCode: 'USD' } };
  } else if (query.includes('on Fulfillment') && ['gid://shopify/Fulfillment/401', 'gid://shopify/Fulfillment/402'].includes(id)) {
    if (!query.includes('displayStatus')) return json(res, 200, { errors: [{ message: 'Missing documented display status field' }] });
    node = { id, order: { id: 'gid://shopify/Order/101' }, status: 'SUCCESS', displayStatus: id.endsWith('402') ? 'LABEL_PRINTED' : 'IN_TRANSIT',
      fulfillmentLineItems: { nodes: [{ lineItem: { id: 'gid://shopify/LineItem/501' } }], pageInfo: { hasNextPage: false } } };
  } else if (id === 'gid://shopify/Order/999') {
    return json(res, 200, { errors: [{ message: 'PRIVATE-UPSTREAM-ERROR' }], data: { node: null } });
  }
  return json(res, 200, { data: { node } });
}).listen(process.env.PORT);
