import { expect, test, type Page } from "@playwright/test";

const FIXTURE_TOKEN = "rslv_ui_test_fixture_key_not_a_real_secret";

async function signIn(page: Page) {
  await page.goto("/workspace");
  await page.getByLabel("Resolve access key").fill(FIXTURE_TOKEN);
  await page.getByRole("button", { name: "Sign in with access key" }).click();
  await expect(
    page.getByRole("button", { name: /Connected refund fixture/ }),
  ).toBeVisible();
}

async function api<T>(page: Page, path: string, body?: unknown): Promise<T> {
  // Same-origin browser fetch, so the request passes the proxy's origin and session checks.
  return page.evaluate(
    async ({ path, body }) => {
      const response = await fetch(
        "/api/resolve" + path,
        body === undefined
          ? {}
          : {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(body),
            },
      );
      if (!response.ok)
        throw new Error(`${path}: ${response.status} ${await response.text()}`);
      return response.json();
    },
    { path, body },
  ) as Promise<T>;
}

test("promise check reads the real backend through the proxy", async ({
  page,
}) => {
  // Hold reconciliation until after "Explain with AI" is clicked, so the panel's reload lands after the
  // explanation (a race first seen in the full suite). The explanation must survive unchanged facts.
  // The gate goes in before sign-in: the inbox selects the first case and starts loading it straight away.
  let release = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/resolve/cases/*/reconciliation", async (route) => {
    await gate;
    await route.continue();
  });
  await signIn(page);
  // Install the gate before navigation can auto-select a case.
  await signIn(page);
  await page.getByRole("button", { name: /Connected refund fixture/ }).click();
  const step = page.getByRole("region", { name: "Next step" });
  const check = page.getByRole("region", { name: "Promise check" });
  // Fixture: accepted $30 refund promise, nothing refunded yet, gated behind a return milestone.
  // Amounts appear once, in the money summary; the promise check shows status and timing only.
  // No fresh provider history exists: missing verification is not a confirmed zero.
  await expect(page.locator(".money-outstanding")).toContainText(
    "Current total unavailable",
  );
  await expect(page.locator(".money-confirmed")).toContainText(
    "Provider check needed",
  );
  await expect(page.locator(".money-confirmed")).not.toContainText("$0.00");
  await expect(check.getByLabel("Promise At risk")).toContainText(
    /Due [A-Z][a-z]{2} \d{1,2}/,
  );
  await expect(check.getByLabel("Promise At risk")).toContainText(
    "0 days since promise",
  );
  await expect(check.locator(".money-rows")).toHaveCount(0);
  // One next step: the refund review is not offered while the return is unconfirmed.
  await expect(
    step.getByRole("heading", { name: "Check before approving" }),
  ).toBeVisible();
  await expect(step.getByRole("button", { name: "Review refund" })).toHaveCount(
    0,
  );
  // The button matches the action: review the unfinished return promise, not refresh evidence.
  await expect(
    step.getByRole("button", { name: "Review promise" }),
  ).toBeVisible();
  await expect(
    step.getByRole("button", { name: "Refresh evidence" }),
  ).toHaveCount(0);

  // Missing information is the next step's checklist, written by code from the same case.
  const missing = step.locator(".checklist li");
  // Ordered steps: the unconfirmed return comes before the missing due date.
  await expect(missing).toHaveText([
    "The return is not confirmed yet.",
    "Add a due date to the refund promise.",
  ]);
  await expect(
    step.getByRole("button", { name: "Explain with AI" }),
  ).toHaveClass(/button-secondary/);
  await expect(
    step.getByText("Advisory only. It never approves or sends a refund."),
  ).toBeVisible();
  // No summary until asked: the checklist and money summary already say it.
  await expect(step.locator(".explain-text")).toHaveCount(0);
  // Short and without repeats: the code template's "return not confirmed → confirm the return" clauses are
  // already the first step, so only the amounts stay.
  const summary =
    "Promised $30.00 after return; $0.00 refunded; $30.00 remaining.";
  // The fixture backend has AI extraction off, so the explanation falls back to the same template.
  const reloaded = page.waitForResponse((response) =>
    /\/promise-health$/.test(new URL(response.url()).pathname),
  );
  await step.getByRole("button", { name: "Explain with AI" }).click();
  await expect(
    step.getByText(/AI explanation not used: AI is turned off on this server/),
  ).toBeVisible();
  await expect(step.locator(".explain-text")).toHaveText(summary);
  release();
  await reloaded;
  await page.waitForTimeout(300);
  await expect(
    step.getByText(/AI explanation not used: AI is turned off on this server/),
  ).toBeVisible();
  await expect(step.locator(".explain-text")).toHaveText(summary);
  await expect(
    step.getByText("AI explanation – verify before acting"),
  ).toHaveCount(0);

  const list = await page.request.get(
    "/api/resolve/resolution-cases/promise-health",
  );
  expect(list.status()).toBe(200);
  const body = await list.json();
  expect(body.overdue_after_days).toBe(3);
  expect(
    body.items.every((item: { status: string }) =>
      ["at_risk", "broken"].includes(item.status),
    ),
  ).toBe(true);
  // Read-only: the proxy does not forward other methods on these paths.
  expect(
    await page.evaluate(
      async () =>
        (
          await fetch("/api/resolve/resolution-cases/promise-health", {
            method: "POST",
          })
        ).status,
    ),
  ).toBe(404);
  const caseId = (
    await (await page.request.get("/api/resolve/resolution-cases")).json()
  ).items.find(
    (item: { title: string }) => item.title === "Connected refund fixture",
  ).id;
  expect(
    await page.evaluate(
      async (id) =>
        (
          await fetch(`/api/resolve/resolution-cases/${id}/next-action`, {
            method: "POST",
          })
        ).status,
      caseId,
    ),
  ).toBe(404);
});

test("the next-step refund button pre-fills the review but never above the backend cap, and sends nothing", async ({
  page,
}) => {
  await signIn(page);
  const capture = "SIMHEALTH" + Date.now();
  const payment = await api<{ id: string }>(page, "/cases", {
    order_id: "ORDER" + capture,
    complaint: "Promise check browser test",
    payment: { capture_id: capture, captured_amount: "100.00" },
    commitment: {
      amount: "30.00",
      status: "accepted",
      source_message: "Agreed refund",
    },
  });
  const created = await api<{ id: string }>(page, "/resolution-cases", {
    title: "Promise check browser test",
    refund_case_id: payment.id,
  });
  await api(page, `/resolution-cases/${created.id}/promises`, {
    promise: "Refund $30",
    source_note: "Support chat",
    target: { kind: "refund", amount: "30.00" },
  });

  // The isolated fixture has no PayPal history, so mark the real reconciliation as current to enable review.
  await page.route(
    `**/api/resolve/cases/${payment.id}/reconciliation`,
    async (route) => {
      const response = await route.fetch();
      route.fulfill({
        response,
        json: { ...(await response.json()), paypal_history_current: true },
      });
    },
  );
  let suggested = "12.50";
  await page.route(
    `**/api/resolve/resolution-cases/${created.id}/promise-health`,
    async (route) => {
      const response = await route.fetch();
      const real = await response.json();
      route.fulfill({
        response,
        json: {
          ...real,
          items: real.items.map((item: Record<string, unknown>) => ({
            ...item,
            status: "at_risk",
            refunded_amount: "17.50",
            remaining_amount: "12.50",
            suggested_refund_amount: suggested,
            days_since_promise: 4,
            overdue: true,
          })),
        },
      });
    },
  );
  const posts: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST")
      posts.push(new URL(request.url()).pathname);
  });

  await page.reload();
  await page
    .getByRole("button", { name: /Promise check browser test/ })
    .click();
  const step = page.getByRole("region", { name: "Next step" });
  await expect(page.locator(".money-status")).toContainText(
    "4 days since promise",
  );
  await expect(page.locator(".money-status")).toContainText("At risk");
  // The single primary action opens the existing review, pre-filled with the suggested amount.
  await step.getByRole("button", { name: "Review refund" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByLabel("Refund amount (USD)")).toHaveValue("12.50");
  await expect(
    dialog.getByRole("button", { name: "Approve $12.50" }),
  ).toBeVisible();
  await dialog.getByRole("button", { name: "Close dialog" }).click();

  // A suggestion above the backend's recommended amount ($30.00 here) is not used.
  suggested = "45.00";
  await page.reload();
  await page
    .getByRole("button", { name: /Promise check browser test/ })
    .click();
  await step.getByRole("button", { name: "Review refund" }).click();
  await expect(dialog.getByLabel("Refund amount (USD)")).toHaveValue("30.00");
  await dialog.getByRole("button", { name: "Close dialog" }).click();
  expect(
    posts.filter((path) => /refund-approvals|refund-executions/.test(path)),
  ).toEqual([]);
});

test("an AI explanation is labelled and changes nothing", async ({ page }) => {
  await signIn(page);
  const text =
    "Promised $30.00 after the return; nothing refunded yet, so confirm the return first.";
  await page.route(
    "**/api/resolve/resolution-cases/*/ai/explain-next-action",
    (route) =>
      route.fulfill({
        json: {
          text,
          source: "ai",
          label: "AI explanation – verify before acting",
          fallback_reason: null,
          cache_hit: false,
        },
      }),
  );
  const posts: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST")
      posts.push(new URL(request.url()).pathname);
  });
  await page.getByRole("button", { name: /Connected refund fixture/ }).click();
  const step = page.getByRole("region", { name: "Next step" });
  await step.getByRole("button", { name: "Explain with AI" }).click();
  await expect(
    step.getByText("AI explanation – verify before acting"),
  ).toBeVisible();
  await expect(step.locator(".explain-text")).toHaveText(
    "Promised $30.00 after the return; nothing refunded yet.",
  );
  expect(
    posts.filter((path) =>
      /refund-approvals|refund-executions|promises/.test(path),
    ),
  ).toEqual([]);
});

test("a linked payment with nothing promised shows the action as the title and ordered steps only", async ({
  page,
}) => {
  await signIn(page);
  const make = async (title: string, agreed: boolean) => {
    const capture = "SIMSTEPS" + Date.now();
    const payment = await api<{ id: string }>(page, "/cases", {
      order_id: "ORDER" + capture,
      complaint: title,
      payment: { capture_id: capture, captured_amount: "100.00" },
      ...(agreed
        ? {
            commitment: {
              amount: "40.00",
              status: "accepted",
              source_message: "Agreed in chat",
            },
          }
        : {}),
    });
    await api(page, "/resolution-cases", {
      title,
      order_reference: "ORD-" + capture,
      refund_case_id: payment.id,
    });
  };
  await make("Steps with agreed amount", true);
  await make("Steps without agreed amount", false);
  await page.reload();

  await page.getByRole("button", { name: /Steps with agreed amount/ }).click();
  const step = page.getByRole("region", { name: "Next step" });
  await expect(
    step.getByRole("heading", { name: "Record the refund promise" }),
  ).toBeVisible();
  await expect(
    step.getByText("The payment is linked, but no refund is promised yet."),
  ).toBeVisible();
  await expect(
    step.getByRole("button", { name: "Record promise" }),
  ).toHaveClass(/button-primary/);
  await expect(step.locator(".checklist li")).toHaveText([
    "Record the refund promise.",
  ]);
  // Nothing is recorded yet, so no summary sentence or AI rewording repeats the checklist.
  await expect(step.locator(".explain")).toHaveCount(0);
  await expect(
    step.getByRole("button", { name: "Explain with AI" }),
  ).toHaveCount(0);
  await expect(step).not.toContainText("{recommended}");

  await page
    .getByRole("button", { name: /Steps without agreed amount/ })
    .click();
  await expect(
    step.getByRole("heading", { name: "Add the agreed refund amount" }),
  ).toBeVisible();
  await expect(step.locator(".checklist li")).toHaveText([
    "Add the agreed refund amount to the linked payment case.",
    "Record the refund promise.",
  ]);
  await expect(step.locator(".explain")).toHaveCount(0);
  // The head's primary action sets the agreed amount; the backend validates it as before.
  await expect(
    step.getByRole("button", { name: "Set agreed amount" }),
  ).toHaveClass(/button-primary/);
  await expect(
    step.getByRole("button", { name: "Record promise" }),
  ).not.toHaveClass(/button-primary/);
  await step.getByRole("button", { name: "Set agreed amount" }).click();
  const form = page.getByRole("dialog", { name: "Set agreed amount" });
  await form.getByLabel("Agreed refund amount (USD)").fill("150.00");
  await form
    .getByLabel("Where it was agreed")
    .fill("Support chat, merchant reply");
  await form.getByRole("button", { name: "Save agreed amount" }).click();
  await expect(form.getByRole("alert")).toBeVisible(); // above the $100.00 capture: rejected by the backend
  await form.getByLabel("Agreed refund amount (USD)").fill("40.00");
  await form.getByRole("button", { name: "Save agreed amount" }).click();
  await expect(form).toHaveCount(0);
  await expect(
    step.getByRole("heading", { name: "Record the refund promise" }),
  ).toBeVisible();
  await expect(step.locator(".checklist li")).toHaveText([
    "Record the refund promise.",
  ]);
});

// The inbox reads merchant-wide promise health once per inbox load. Mocked list responses (synthetic data)
// prove the rows render with the flags, and still render plainly when the call fails or returns nothing.
test("the inbox renders with and without promise-health data", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await signIn(page);
  const inbox = await api<{ items: { id: string; title: string }[] }>(
    page,
    "/resolution-cases/inbox?limit=50&offset=0&filter_by=all&q=",
  );
  const fixture = inbox.items.find((row) =>
    /Connected refund fixture/.test(row.title),
  )!;
  const row = page.getByRole("button", { name: /Connected refund fixture/ });
  const healthList = "**/api/resolve/resolution-cases/promise-health?*";

  await page.route(healthList, (route) =>
    route.fulfill({
      json: {
        items: [
          {
            case_id: fixture.id,
            promise_id: "synthetic-promise",
            promise: "Refund",
            status: "broken",
            currency: "USD",
            promised_amount: "40.00",
            refunded_amount: "0.00",
            pending_amount: "0.00",
            remaining_amount: "40.00",
            captured_amount: "100.00",
            suggested_refund_amount: "40.00",
            deadline: "2026-11-01T00:00:00Z",
            days_since_promise: 9,
            overdue: true,
            ledger_ahead_of_provider: false,
          },
        ],
      },
    }),
  );
  await page.reload();
  await expect(row).toBeVisible();
  await expect(row.locator(".case-row-risk")).toHaveText("$40.00 at risk");
  await expect(row.getByText("Overdue")).toBeVisible();

  for (const failure of [
    (route: Parameters<Parameters<Page["route"]>[1]>[0]) =>
      route.fulfill({ status: 500, json: { detail: "synthetic failure" } }),
    (route: Parameters<Parameters<Page["route"]>[1]>[0]) =>
      route.fulfill({ json: { items: [] } }),
  ]) {
    await page.unroute(healthList);
    await page.route(healthList, failure);
    await page.reload();
    await expect(row).toBeVisible();
    await expect(page.locator(".case-row-risk")).toHaveCount(0);
  }
  expect(errors).toEqual([]);
});

// After the main merge: our overview structure on the deferred-loading markup. Collapsed sections make no
// request until opened, and the timeline card says how to load events instead of loading forever.
test("the overview keeps its cards and defers investigation, Zendesk and events", async ({
  page,
}) => {
  const paths: string[] = [];
  page.on("request", (request) => paths.push(new URL(request.url()).pathname));
  await signIn(page);
  await page.getByRole("button", { name: /Connected refund fixture/ }).click();
  const step = page.getByRole("region", { name: "Next step" });
  await expect(
    step.getByRole("button", { name: "Review promise" }),
  ).toBeEnabled();
  for (const area of ["Case summary", "Promises & AI", "Timeline"])
    await expect(page.getByRole("region", { name: area })).toBeVisible();
  await expect(
    page
      .getByRole("region", { name: "Case summary" })
      .getByRole("region", { name: "Next step" }),
  ).toBeVisible();
  for (const suffix of ["/investigations", "/helpdesk", "/timeline"])
    expect(
      paths.some((path) => path.endsWith(suffix)),
      suffix,
    ).toBe(false);

  const timeline = page.getByRole("region", { name: "Timeline" });
  await expect(
    timeline.getByText("Events load when you open the evidence timeline."),
  ).toBeVisible();
  const investigation = page
    .locator("details.details-card")
    .filter({ hasText: "Automatic investigation details" });
  await expect(investigation).not.toHaveAttribute("open", "");
  await investigation.locator("summary").click();
  await expect(
    investigation.getByRole("region", { name: "Automatic investigation" }),
  ).toBeVisible();
  const zendesk = page
    .locator("details.details-card")
    .filter({ hasText: "Zendesk ticket" });
  await zendesk.locator("summary").click();
  await expect(
    zendesk.getByText(/Connect Zendesk|Zendesk ticket ID/).first(),
  ).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(
    390,
  );
  await timeline.getByRole("button", { name: "Show events" }).click();
  await expect(
    page.getByRole("button", { name: "Evidence timeline", exact: true }),
  ).toHaveAttribute("aria-current", "page");
});

// Our overview components after the cleanup. Promise data for the paused check is a mocked (synthetic) response.
test.describe("overview cleanup", () => {
  test.use({ timezoneId: "Pacific/Kiritimati" }); // UTC+14, so local dates differ from UTC ones

  test("review promise opens the unfinished prerequisite; suggestions start as one line; due dates are local", async ({
    page,
  }) => {
    await signIn(page);
    await page
      .getByRole("button", { name: /Connected refund fixture/ })
      .click();
    const step = page.getByRole("region", { name: "Next step" });
    const returnRow = page
      .locator(".promise-section .promise-row")
      .filter({
        has: page.locator("summary", { hasText: "Return milestone" }),
      });
    await expect(returnRow).not.toHaveAttribute("open", "");
    await step.getByRole("button", { name: "Review promise" }).click();
    await expect(returnRow).toHaveAttribute("open", "");
    await expect(returnRow.locator("summary")).toBeFocused();
    await expect(returnRow.locator(".promise-reason")).toBeInViewport();

    const suggestions = page.getByRole("region", {
      name: "Promise suggestions",
    });
    await expect(suggestions.locator(".extraction-line")).toContainText(
      "Suggestions only. Nothing is saved or paid until you confirm.",
    );
    await expect(
      suggestions.getByRole("button", {
        name: "Extract promises from conversation",
      }),
    ).toBeVisible();
    await expect(suggestions.getByText(/No suggestions yet/)).toHaveCount(0);

    const id = (
      await api<{ items: { id: string; title: string }[] }>(
        page,
        "/resolution-cases/inbox?limit=50&offset=0&filter_by=all&q=",
      )
    ).items.find((row) => row.title === "Connected refund fixture")!.id;
    const health = await api<{ items: { deadline: string }[] }>(
      page,
      `/resolution-cases/${id}/promise-health`,
    );
    const local = new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "numeric",
      timeZone: "Pacific/Kiritimati",
    }).format(new Date(health.items[0].deadline));
    await expect(
      page.getByRole("region", { name: "Promise check" }).locator(".due-label"),
    ).toHaveText(`Due ${local}`);
    await expect(page.locator(".money-summary .due-label")).toHaveText(
      `Due ${local}`,
    );
  });

  test("the promise check says it is paused while the refund promise needs review", async ({
    page,
  }) => {
    await page.route(
      /\/api\/resolve\/resolution-cases\/[0-9a-f-]{36}$/,
      async (route) => {
        const response = await route.fetch();
        const body = await response.json();
        for (const promise of body.promises ?? [])
          if (promise.terms?.target?.kind === "refund")
            promise.outcome = "needs_review";
        await route.fulfill({ response, json: body });
      },
    );
    await page.route(
      /\/api\/resolve\/resolution-cases\/[0-9a-f-]{36}\/promise-health$/,
      (route) =>
        route.fulfill({
          json: {
            case_id: new URL(route.request().url()).pathname.split("/").at(-2),
            overdue_after_days: 3,
            items: [],
          },
        }),
    );
    await signIn(page);
    await page
      .getByRole("button", { name: /Connected refund fixture/ })
      .click();
    const check = page.getByRole("region", { name: "Promise check" });
    await expect(
      check.getByText("Paused – promise needs review"),
    ).toBeVisible();
    await expect(check.getByText(/No accepted refund promise/)).toHaveCount(0);
  });
});
