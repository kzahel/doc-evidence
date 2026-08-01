import { expect, test } from "@playwright/test";

const token = process.env.DOC_EVIDENCE_E2E_TOKEN!;
const firstLibrary = process.env.DOC_EVIDENCE_E2E_FIRST_LIBRARY!;
const secondLibrary = process.env.DOC_EVIDENCE_E2E_SECOND_LIBRARY!;
const firstDocument = process.env.DOC_EVIDENCE_E2E_FIRST_DOCUMENT!;
const secondDocument = process.env.DOC_EVIDENCE_E2E_SECOND_DOCUMENT!;

test("runs, cancels, times out, reuses cache, and isolates libraries", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(error.message));

  await page.goto(`/?library=${firstLibrary}&document=${firstDocument}&page=1#token=${token}`);
  await expect(page.getByRole("heading", { name: "first.pdf" })).toBeVisible();
  await expect(page.getByLabel("Active library")).toHaveValue(firstLibrary);
  await expect(page).toHaveURL(new RegExp(`library=${firstLibrary}.*document=${encodeURIComponent(firstDocument)}`));
  expect(new URL(page.url()).hash).toBe("");
  await expect(page.getByRole("button", { name: /Activity/ })).toContainText("0 active");

  const success = page.locator("article").filter({ hasText: "Fixture success" });
  await success.getByRole("button", { name: "Run extraction" }).click();
  await expect(success.getByRole("button", { name: "Use cached result" })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("fixture evidence", { exact: false }).first()).toBeVisible();

  await success.getByRole("button", { name: "Use cached result" }).click();
  await page.getByRole("button", { name: /Activity/ }).click();
  await page.getByRole("button", { name: "Recent", exact: true }).click();
  await expect(page.getByText("Fulfilled from exact cache; no worker started")).toBeVisible();
  await page.getByLabel("Close activity").click();

  const cancellable = page.locator("article").filter({ hasText: "Fixture cancellable" });
  await cancellable.getByRole("button", { name: "Run extraction" }).click();
  await expect(cancellable.getByRole("button", { name: /Cancel (starting|running)/ })).toBeVisible();
  await cancellable.getByRole("button", { name: /Cancel (starting|running)/ }).click();
  await page.getByRole("button", { name: /Activity/ }).click();
  await page.getByRole("button", { name: "Cancelled", exact: true }).click();
  await expect(page.getByRole("button", { name: /fixture-cancellable.*cancelled/i })).toBeVisible({ timeout: 20_000 });
  await page.getByLabel("Close activity").click();

  const timeout = page.locator("article").filter({ hasText: "Fixture timeout" });
  await timeout.getByRole("button", { name: "Run extraction" }).click();
  await page.getByRole("button", { name: /Activity/ }).click();
  await page.getByRole("button", { name: "Failed", exact: true }).click();
  const timedOutJob = page.getByRole("button", { name: /fixture-timeout.*failed/i });
  await expect(timedOutJob).toBeVisible({ timeout: 20_000 });
  await timedOutJob.click();
  await page.getByRole("button", { name: "Advanced debug" }).click();
  await expect(page.getByText(/Process not alive/).first()).toBeVisible();
  await expect(page.getByText(/timeout:/).first()).toBeVisible();
  await expect(page.getByText("Event timeline")).toBeVisible();
  await page.getByLabel("Close activity").click();

  await page.getByLabel("Active library").selectOption(secondLibrary);
  await expect(page.getByRole("heading", { name: "second.pdf" })).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`library=${secondLibrary}.*document=${encodeURIComponent(secondDocument)}`));
  await expect(page.getByRole("button", { name: /Activity/ })).toContainText("0 active · 0 queued · 0 failed");

  await page.goto(`/?library=${firstLibrary}&document=${firstDocument}&page=1#token=${token}`);
  await expect(page.getByRole("heading", { name: "first.pdf" })).toBeVisible();
  await page.getByRole("button", { name: /Activity/ }).click();
  await page.getByRole("button", { name: "Failed", exact: true }).click();
  await expect(page.getByRole("button", { name: /fixture-timeout.*failed/i })).toBeVisible();
  expect(consoleErrors).toEqual([]);
});
