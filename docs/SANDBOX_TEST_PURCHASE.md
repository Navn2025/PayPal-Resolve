# Make a sandbox test purchase and verify it in Resolve

This walkthrough creates and captures one **USD 1.00 sandbox purchase**. It uses
PowerShell requests and PayPal's browser approval page; no frontend is required.
The commands target the sandbox host throughout. They are manual test commands,
not a refund executor or a production checkout implementation.

On 2026-11-07, the configured application's OAuth token exchange succeeded against
real PayPal Sandbox. The owner subsequently reported a completed USD 1.00 purchase,
and the application's client successfully read that capture, matching its ID,
amount, currency and configured seller. An authenticated Resolve case saved the
capture evidence, and the bounded executor subsequently refunded the test purchase
in full, confirmed by an independent refund read. The commands below were checked against the
official API reference and parsed for PowerShell syntax; the assistant did not
execute order/capture writes. The buyer must approve in the browser before capture.

## 1. Prepare a buyer

Keep your existing Business sandbox seller and its configured REST app.

For this walkthrough, use a **Personal sandbox buyer with Country/Region United
States**. Your earlier account list showed both default accounts as IN. PayPal
documents India payments as international-only; a US buyer/IN seller test avoids
depending on domestic support. The original IN-to-IN sandbox pair has not been
tested here. See [PayPal's India payment guidance](https://www.paypal.com/in/cshelp/article/can-i-use-paypal-to-receive-payments-from-indian-customers-help1049).

In the [Developer Dashboard](https://developer.paypal.com/dashboard/), select
**Testing Tools > Sandbox Accounts > Create account**, choose **Personal** and
**United States**, and create the test account. Use its menu's **View/Edit account**
to obtain its login email and password. These credentials are for browser approval.
Do not change your seller's app credentials or merchant ID to the buyer's values.
[Sandbox account instructions](https://developer.paypal.com/sandbox-testing/accounts/).

## 2. Open a second PowerShell terminal

Keep the backend running in its original terminal. Use a new terminal for every
block below, in order, keeping that second terminal open so its variables survive:

```powershell
cd C:\Users\navne\Desktop\paypal-resolve\backend
```

## 3. Authenticate the seller app

Run this block. At its prompts, enter the same **sandbox REST app client ID and
client secret** already saved in your local `.env`. The secret prompt is masked.
The credentials and OAuth token stay in variables; do not print or share them.
This does not ask for the seller's login password or the Resolve API token.

```powershell
$resolveSandboxClientId = Read-Host "Sandbox REST app client ID"
$resolveSandboxSecret = Read-Host "Sandbox REST app client secret" -AsSecureString
$resolveSandboxCredential = [pscredential]::new($resolveSandboxClientId, $resolveSandboxSecret)
$resolveSandboxBasic = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(
    $resolveSandboxClientId + ':' + $resolveSandboxCredential.GetNetworkCredential().Password
))
$resolveSandboxToken = Invoke-RestMethod -Method Post -Uri 'https://api-m.sandbox.paypal.com/v1/oauth2/token' -Headers @{ Authorization = "Basic $resolveSandboxBasic" } -ContentType 'application/x-www-form-urlencoded' -Body @{ grant_type = 'client_credentials' } -MaximumRedirection 0 -TimeoutSec 20 -ErrorAction Stop
if (-not $resolveSandboxToken.access_token -or $resolveSandboxToken.token_type -ne 'Bearer') {
    throw 'No valid sandbox bearer token was returned. Stop here.'
}
if (-not (Get-Variable -Name resolveSandboxCreateRequestId -ErrorAction SilentlyContinue)) {
    $resolveSandboxCreateRequestId = [guid]::NewGuid().ToString()
}
if (-not (Get-Variable -Name resolveSandboxCaptureRequestId -ErrorAction SilentlyContinue)) {
    $resolveSandboxCaptureRequestId = [guid]::NewGuid().ToString()
}
Write-Host 'Sandbox authentication succeeded.'
```

This follows PayPal's [client-credentials authentication](https://developer.paypal.com/api/rest/authentication/).

## 4. Create the USD 1.00 order

Run this block once for the purchase. The request UUID is kept separately so a
retry of this block in the same terminal reuses it. Creating the order does not
complete the purchase; buyer approval and capture follow.

```powershell
$resolveSandboxHeaders = @{
    Authorization = "Bearer $($resolveSandboxToken.access_token)"
    Prefer = 'return=representation'
    'PayPal-Request-Id' = $resolveSandboxCreateRequestId
}
$resolveSandboxBody = @'
{
  "intent": "CAPTURE",
  "purchase_units": [{
    "description": "Resolve sandbox verification test",
    "amount": {"currency_code": "USD", "value": "1.00"}
  }],
  "payment_source": {
    "paypal": {
      "experience_context": {
        "return_url": "http://localhost:8000/docs",
        "cancel_url": "http://localhost:8000/docs",
        "user_action": "PAY_NOW",
        "shipping_preference": "NO_SHIPPING"
      }
    }
  }
}
'@
$resolveSandboxOrder = Invoke-RestMethod -Method Post -Uri 'https://api-m.sandbox.paypal.com/v2/checkout/orders' -Headers $resolveSandboxHeaders -ContentType 'application/json' -Body $resolveSandboxBody -MaximumRedirection 0 -TimeoutSec 20 -ErrorAction Stop
$resolveSandboxApprovalUrl = $resolveSandboxOrder.links | Where-Object { $_.rel -in @('payer-action', 'approve') } | Select-Object -First 1 -ExpandProperty href
if (-not $resolveSandboxOrder.id -or -not $resolveSandboxApprovalUrl) {
    throw 'No order ID/approval link was returned. Stop here.'
}
Write-Host "Order ID: $($resolveSandboxOrder.id)"
Write-Host "Approval URL: $resolveSandboxApprovalUrl"
```

The payload uses the current `payment_source.paypal.experience_context` fields,
rather than the deprecated `application_context` fields.
[Create order reference](https://developer.paypal.com/api/orders/v2/orders-create).

## 5. Approve in a private browser window

Copy the printed **Approval URL** into an Incognito/InPrivate window. Check that
the page is on `sandbox.paypal.com`. Sign in using the **Personal buyer** from
step 1, review **USD 1.00**, and approve the test purchase. A private window keeps
your existing seller session separate from the buyer session.

PayPal redirects to the local `/docs` page used as the return destination. That
redirect is not a capture confirmation. Keep the PowerShell variables intact
and continue to the capture step. If the redirect cannot open, inspect order
status in the next step before deciding whether to repeat approval.
[Documented approval/capture flow](https://developer.paypal.com/whats-an-order/).

## 6. Capture the approved order

Run in the **same second terminal**. It reads the order first. An already
completed order is read back, while an approved order is captured using the
previously allocated capture request UUID. Other states stop with a message.

```powershell
$resolveSandboxReadHeaders = @{
    Authorization = "Bearer $($resolveSandboxToken.access_token)"
}
$resolveSandboxOrderUrl = "https://api-m.sandbox.paypal.com/v2/checkout/orders/$($resolveSandboxOrder.id)"
$resolveSandboxCurrent = Invoke-RestMethod -Method Get -Uri $resolveSandboxOrderUrl -Headers $resolveSandboxReadHeaders -MaximumRedirection 0 -TimeoutSec 20 -ErrorAction Stop
if ($resolveSandboxCurrent.status -eq 'COMPLETED') {
    $resolveSandboxCaptured = $resolveSandboxCurrent
} elseif ($resolveSandboxCurrent.status -eq 'APPROVED') {
    $resolveSandboxCaptureHeaders = @{
        Authorization = "Bearer $($resolveSandboxToken.access_token)"
        Prefer = 'return=representation'
        'PayPal-Request-Id' = $resolveSandboxCaptureRequestId
    }
    $resolveSandboxCaptured = Invoke-RestMethod -Method Post -Uri "$resolveSandboxOrderUrl/capture" -Headers $resolveSandboxCaptureHeaders -ContentType 'application/json' -Body '{}' -MaximumRedirection 0 -TimeoutSec 20 -ErrorAction Stop
} else {
    throw "Order is $($resolveSandboxCurrent.status). Finish buyer approval before capture."
}
$resolveSandboxCapture = $resolveSandboxCaptured.purchase_units[0].payments.captures[0]
if (-not $resolveSandboxCapture.id) {
    throw 'No capture ID was returned. Stop and inspect the order status.'
}
Write-Host "Order ID: $($resolveSandboxOrder.id)"
Write-Host "Capture ID: $($resolveSandboxCapture.id)"
Write-Host "Capture status: $($resolveSandboxCapture.status)"
Write-Host "Amount: $($resolveSandboxCapture.amount.value) $($resolveSandboxCapture.amount.currency_code)"
```

Expect a capture with `COMPLETED`, `1.00`, and `USD`. The **capture ID** is nested
under `purchase_units[].payments.captures[]`; the top-level `id` is the order ID.
The separate capture request UUID is for retries of this one operation. After a
timeout, rerun this capture block in the same terminal, keeping the UUID unchanged;
it reads order state before submitting again. This is a manual sandbox workflow,
not a durable production execution system. If the token expires, authenticate
again before issuing more requests; do not recreate/approve a second purchase
just to recover a lost response.
[Capture reference](https://developer.paypal.com/api/orders/v2/orders-capture) and
[order lookup](https://developer.paypal.com/api/orders/v2/orders-get).

If approval/capture is denied, stop and retain only a sanitized error code/message.
Do not post secrets, Authorization headers, or full token objects in chat. A pending
capture has not established completion; check its status rather than assuming it
settled. Close this second terminal when the walkthrough is finished.

## 7. Verify the capture in Resolve

In [Resolve API docs](http://127.0.0.1:8000/docs), authorize with your local
Resolve token. Execute `POST /cases` using the two printed IDs:

```json
{
  "order_id": "PASTE_THE_ORDER_ID",
  "complaint": "Sandbox capture verification test",
  "payment": {
    "capture_id": "PASTE_THE_CAPTURE_ID",
    "captured_amount": "1.00",
    "currency": "USD"
  }
}
```

Copy the case response's `id`, then execute
`POST /cases/{case_id}/paypal-capture-verifications` for that case with no body.
The result should identify the sandbox capture, amount, payee and observed status.
Missing payee or a mismatch must be resolved, not bypassed. See the saved history
and reconciliation using their GET endpoints.

A successful capture-details check still reports refund history and eligibility
unverified. This case has no refund commitment and no financial execution action.
