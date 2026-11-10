const $ = (id) => document.getElementById(id);
const amount = (cents) => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);
let products = [];
let enabled = false;
let busy = false;
let cart = {};
let retryAction = null;
try {
  const saved = JSON.parse(localStorage.getItem("field-brew-cart") || "{}");
  if (saved && typeof saved === "object" && !Array.isArray(saved)) cart = saved;
} catch { /* A browser can deny local storage. */ }

function readSession(key) {
  try { return sessionStorage.getItem(key); } catch { return null; }
}
function writeSession(key, value) {
  try { sessionStorage.setItem(key, value); } catch { /* Optional browser state. */ }
}
async function api(route, data) {
  const response = await fetch(route, {
    method: data ? "POST" : "GET",
    headers: data ? { "Content-Type": "application/json" } : {},
    body: data ? JSON.stringify(data) : undefined,
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.message || "The store could not complete this request.");
  return result;
}
function lines() {
  return products.filter(item => Number.isInteger(cart[item.id]) && cart[item.id] > 0)
    .map(item => ({ ...item, quantity: Math.min(10, cart[item.id]) }));
}
function drawCart() {
  const items = lines();
  $("cart-count").textContent = items.reduce((n, item) => n + item.quantity, 0);
  $("cart-total").textContent = amount(items.reduce((sum, item) => sum + item.cents * item.quantity, 0));
  $("cart-items").innerHTML = items.length ? items.map(item => `
    <div class="cart-row"><div><strong>${item.name}</strong><br>${amount(item.cents)} each</div>
    <div class="qty"><button type="button" data-product="${item.id}" data-step="-1" aria-label="Remove one ${item.name}">−</button>
    <span>${item.quantity}</span><button type="button" data-product="${item.id}" data-step="1" aria-label="Add one ${item.name}" ${item.quantity === 10 ? "disabled" : ""}>+</button></div></div>
  `).join("") : '<p class="empty">Your cart is empty. Pick something for the next brew.</p>';
  $("checkout").disabled = !enabled || !items.length || busy;
}
function storeCart() {
  try { localStorage.setItem("field-brew-cart", JSON.stringify(cart)); } catch { /* Optional. */ }
}
function change(id, step) {
  const product = products.find(item => item.id === id);
  if (!product || busy) return;
  const next = Math.max(0, Math.min(10, (Number.isInteger(cart[id]) ? cart[id] : 0) + step));
  if (next) cart[id] = next;
  else delete cart[id];
  $("cart-announcement").textContent = product.name + ": " + next + " in your cart.";
  storeCart();
  drawCart();
}
function drawProducts() {
  $("products").innerHTML = products.map((item, index) => `
    <article class="product"><div class="art ${item.tone}" aria-hidden="true"><small>${String(index + 1).padStart(2, "0")} / ${item.kind}</small>
    <svg viewBox="0 0 320 220"><use href="/products.svg#${item.id}"></use></svg></div>
    <div class="product-body"><div class="product-title"><h3>${item.name}</h3><span class="price">${amount(item.cents)}</span></div>
    <p>${item.note}</p><button class="add" type="button" data-product="${item.id}" aria-label="Add ${item.name} to cart">Add to cart <span aria-hidden="true">+</span></button></div></article>
  `).join("");
}
$("products").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-product]");
  if (button) change(button.dataset.product, 1);
});
$("cart-items").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-product]");
  if (!button) return;
  change(button.dataset.product, Number(button.dataset.step));
  const replacement = [...$("cart-items").querySelectorAll("button")].find(item =>
    item.dataset.product === button.dataset.product && item.dataset.step === button.dataset.step && !item.disabled);
  (replacement || $("close-cart")).focus();
});
$("open-cart").addEventListener("click", () => {
  drawCart();
  $("cart-message").textContent = enabled ? "You’ll review the test purchase at PayPal." : "Checkout requires PayPal Sandbox and Resolve configuration.";
  $("cart").showModal();
});
$("close-cart").addEventListener("click", () => $("cart").close());
$("checkout").addEventListener("click", async () => {
  if (busy) return;
  busy = true;
  drawCart();
  $("cart-message").textContent = "Preparing your Sandbox order…";
  try {
    const items = lines().map(({ id, quantity }) => ({ id, quantity }));
    const snapshot = JSON.stringify(items);
    let request = {};
    try { request = JSON.parse(readSession("field-brew-checkout") || "{}"); } catch { /* Start fresh. */ }
    if (!request.id || request.snapshot !== snapshot) request = { id: crypto.randomUUID(), snapshot };
    writeSession("field-brew-checkout", JSON.stringify(request));
    const created = await api("/api/orders", { requestId: request.id, items });
    writeSession("field-brew-receipt", created.id);
    if (created.state === "completed") {
      location.assign("/?order=" + encodeURIComponent(created.id));
      return;
    }
    location.assign(created.approvalUrl);
  } catch (error) {
    $("cart-message").textContent = error.message;
    busy = false;
    drawCart();
  }
});

function detail(term, value) {
  const dt = document.createElement("dt");
  const dd = document.createElement("dd");
  dt.textContent = term;
  dd.textContent = value;
  $("receipt-details").append(dt, dd);
}
const names = {
  paypal_order_id: "PayPal order", paypal_capture_id: "PayPal capture",
  currency: "Currency", payment_status: "Payment status",
  captured_amount: "Captured amount", refunded_amount: "Refunded amount",
};
let supportOrder = null;
function paintReceipt(result) {
  supportOrder = result.id;
  $("order-support").hidden = !(result.state === "completed" && result.caseId);
  $("receipt").hidden = false;
  $("receipt-details").replaceChildren();
  $("receipt-checks").replaceChildren();
  const paid = result.state === "completed";
  $("receipt-title").textContent = paid ? "Payment confirmed" : result.state === "pending" ? "Payment pending" : "Awaiting approval";
  $("receipt-message").textContent = paid
    ? result.resolveUnavailable ? "PayPal captured the test payment. Resolve couldn’t finish checking it; retry without paying again."
      : "PayPal captured this Sandbox payment. The Resolve check appears below."
    : result.state === "pending" ? "PayPal has a pending capture. Check its status again without creating a new payment."
      : "PayPal hasn’t approved this order yet.";
  detail("Store order", result.reference);
  detail("Total", "$" + result.total + " USD");
  if (result.caseId) detail("Resolve case", result.caseId);
  if (result.comparison) {
    const resultText = result.comparison.status === "match" ? "Matched PayPal"
      : result.comparison.status === "mismatch" ? "Difference found" : "Needs more evidence";
    detail("Resolve evidence", result.resolveUnavailable ? resultText + " (last saved check)" : resultText);
    if (result.comparison.checkedAt) detail("Checked at", new Date(result.comparison.checkedAt).toLocaleString());
    for (const item of result.comparison.checks) {
      const pill = document.createElement("span");
      pill.className = "check";
      pill.dataset.state = item.status;
      pill.textContent = (names[item.field] || item.field) + ": " + item.status.replaceAll("_", " ");
      if (item.status === "mismatch" && item.app !== undefined) {
        pill.textContent += " (store " + (item.app ?? "—") + "; PayPal " + (item.paypal ?? "—") + ")";
      }
      $("receipt-checks").append(pill);
    }
  }
  if (paid) {
    const checkout = readSession("field-brew-receipt");
    if (checkout === result.id) {
      cart = {};
      storeCart();
      writeSession("field-brew-checkout", "");
      writeSession("field-brew-receipt", "");
      drawCart();
    }
  }
}

function showError(error, fallbackTitle) {
  $("receipt").hidden = false;
  $("receipt-title").textContent = fallbackTitle;
  $("receipt-message").textContent = error.message;
}

async function finish() {
  const url = new URL(location.href);
  const mode = url.searchParams.get("checkout");
  const id = url.searchParams.get("order");
  if (!id) return;
  const callback = url.searchParams.get("token");
  const key = "field-brew-paypal-" + id;
  if (callback && mode === "approved") writeSession(key, callback);
  const token = callback || readSession(key);
  const route = "/api/orders/" + encodeURIComponent(id);
  history.replaceState(null, "", "/?order=" + encodeURIComponent(id));
  $("receipt").hidden = false;
  $("receipt").scrollIntoView({ block: "start" });
  if (mode === "cancelled") {
    $("receipt-title").textContent = "Checkout cancelled";
    $("receipt-message").textContent = "Nothing was captured. Your cart is still here.";
    return;
  }
  retryAction = async () => {
    const existing = await api(route);
    if (existing.state === "completed") return api(route + "/verify", {});
    if (!token) return existing;
    return api(route + "/capture", { token });
  };
  $("retry").hidden = false;
  $("retry").disabled = true;
  try {
    $("receipt-title").textContent = "Checking your Sandbox order…";
    const initial = mode === "approved" && token ? await api(route + "/capture", { token }) : await api(route);
    paintReceipt(initial);
  } catch (error) {
    showError(error, "Checkout needs another check");
  } finally {
    $("retry").disabled = false;
  }
}
$("retry").addEventListener("click", async () => {
  if (!retryAction) return;
  $("retry").disabled = true;
  try { paintReceipt(await retryAction()); }
  catch (error) { $("receipt-message").textContent = error.message; }
  finally { $("retry").disabled = false; }
});

try {
  const payload = await api("/api/catalog");
  products = payload.catalog;
  enabled = payload.checkoutEnabled;
  drawProducts();
  drawCart();
  await finish();
} catch (error) {
  $("catalog-error").textContent = error.message;
  $("catalog-error").hidden = false;
}


async function support(action, input = {}) {
  if (!supportOrder) throw new Error("Open your paid order first.");
  return api("/api/orders/" + encodeURIComponent(supportOrder) + "/" + action, input);
}
function showResolution(result) {
  $("support-progress").textContent = result.stage === "no_issue" ? "You can report an issue with this order." : result.next_step.action + (result.next_step.overdue ? " This update is overdue." : "");
}
$("support-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const values = Object.fromEntries(new FormData(form));
  const storageKey = "field-brew-support:" + supportOrder;
  let saved = {};
  try { saved = JSON.parse(readSession(storageKey) || "{}"); } catch { /* Use a new request. */ }
  const fingerprint = JSON.stringify(values);
  if (saved.fingerprint !== fingerprint) saved = { fingerprint, requestId: crypto.randomUUID() };
  writeSession(storageKey, JSON.stringify(saved));
  form.querySelector("button").disabled = true;
  try {
    await support("support", { ...values, requestId: saved.requestId });
    $("support-progress").textContent = "Your request is with the support team. A requested refund or replacement needs merchant review.";
  } catch (error) { $("support-progress").textContent = error.message; }
  finally { form.querySelector("button").disabled = false; }
});
$("refresh-support").addEventListener("click", async () => {
  try { showResolution(await support("resolution")); }
  catch (error) { $("support-progress").textContent = error.message; }
});
$("open-support").addEventListener("click", async () => {
  try {
    const link = await support("support-link");
    if (!link.public_url) throw new Error("The merchant must configure its customer portal URL.");
    const url = new URL(link.public_url);
    if (url.protocol !== "https:" && !(url.protocol === "http:" && ["localhost", "127.0.0.1"].includes(url.hostname))) throw new Error("The customer portal URL is unavailable.");
    location.assign(url.href);
  } catch (error) { $("support-progress").textContent = error.message; }
});

$("refund-journey").addEventListener("click",async()=>{
  try {const journey=await support("refund-journey");$("support-detail").textContent=journey.explanation+" "+journey.traces.map(trace=>trace.reference_type+": "+trace.reference+" (merchant-recorded)").join("; ");}
  catch(error){$("support-detail").textContent=error.message;}
});
$("return-options").addEventListener("click",async()=>{
  try {const result=await support("return-eligibility");$("support-detail").textContent=(result.decision==="eligible"?"Return request can be reviewed under the configured policy. ":"Merchant review needed: "+result.flags.join("; ")+". ")+(result.policy_enabled?"Return shipping paid by "+result.shipping_paid_by+". Merchant-stated fee: "+result.currency+" "+result.restocking_fee+". ":"The merchant will confirm eligibility, shipping costs and any applicable fees before you ship. ")+result.instructions;}
  catch(error){$("support-detail").textContent=error.message;}
});
$("saved-context").addEventListener("click",async()=>{
  try {const result=await support("context");$("support-detail").textContent=result.issues.length?result.issues.map(issue=>issue.message+" Requested: "+issue.requested_resolution).join(" "):"No support report has been submitted for this order.";}
  catch(error){$("support-detail").textContent=error.message;}
});
