import { expect, test } from "@playwright/test";

const token = process.env.DOC_EVIDENCE_E2E_TOKEN;
const libraryId = process.env.DOC_EVIDENCE_PRIVATE_LIBRARY;
const ocrDocument = process.env.DOC_EVIDENCE_PRIVATE_OCR_DOCUMENT;
const layoutDocument = process.env.DOC_EVIDENCE_PRIVATE_LAYOUT_DOCUMENT;
const layoutExtractor = process.env.DOC_EVIDENCE_PRIVATE_LAYOUT_EXTRACTOR;
const layoutDisplay = process.env.DOC_EVIDENCE_PRIVATE_LAYOUT_DISPLAY;
const candidates = process.env.DOC_EVIDENCE_PRIVATE_PREFLIGHT_CANDIDATES;
const executions = process.env.DOC_EVIDENCE_PRIVATE_PREFLIGHT_EXECUTIONS;

test.skip(!ocrDocument, "authorized private integration environment is not configured");
test.setTimeout(300_000);

test("executes one OCR, reuses layout, and only preflights the broad batch", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(error.message));

  await page.goto(`/?library=${libraryId}&document=${ocrDocument}&page=1#token=${token}`);
  await expect(page.getByLabel("Active library")).toHaveValue(libraryId!);
  const ocr = page.locator("article").filter({ hasText: "OCRmyPDF + Tesseract" });
  await expect(ocr.getByText("Recommended")).toBeVisible({ timeout: 45_000 });
  await ocr.getByRole("button", { name: "Run extraction" }).click();
  await expect(ocr.getByRole("button", { name: "Use cached result" })).toBeVisible({ timeout: 240_000 });
  await ocr.getByRole("button", { name: "Use cached result" }).click();

  await page.getByRole("button", { name: /Activity/ }).click();
  await page.getByRole("button", { name: "Recent", exact: true }).click();
  await expect(page.getByRole("button", {
    name: /ocrmypdf-tesseract succeeded.*Fulfilled from exact cache; no worker started/,
  }).first()).toBeVisible();
  await page.getByRole("button", { name: "Preflight batch" }).click();
  await expect(page.getByText(`${candidates} image-only PDF candidates`)).toBeVisible();
  await expect(page.getByText(`${executions} actual OCR executions`)).toBeVisible();
  await expect(page.getByRole("button", { name: new RegExp(`Confirm ${executions} OCR executions`) })).toBeVisible();
  await page.getByLabel("Close activity").click();

  await page.goto(`/?library=${libraryId}&document=${layoutDocument}&page=1#token=${token}`);
  const layout = page.locator("article").filter({ hasText: layoutDisplay! });
  await expect(layout.getByText("Exact run cached")).toBeVisible({ timeout: 30_000 });
  await layout.getByRole("button", { name: "Use cached result" }).click();
  await page.getByRole("button", { name: /Activity/ }).click();
  await page.getByRole("button", { name: "Recent", exact: true }).click();
  await expect(page.getByRole("button", {
    name: new RegExp(`${layoutExtractor} succeeded.*Fulfilled from exact cache; no worker started`),
  }).first()).toBeVisible();
  expect(consoleErrors).toEqual([]);
});
