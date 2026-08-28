import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  const externalRequests = [];
  page.on("request", (request) => {
    const host = new URL(request.url()).hostname;
    if (!["127.0.0.1", "localhost"].includes(host)) externalRequests.push(request.url());
  });
  page.externalRequests = externalRequests;

  await page.goto("/login");
  await page.getByLabel("Пользователь").fill("visual-admin");
  await page.getByLabel("Пароль").fill("visual-admin-password");
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page).toHaveURL(/\/dashboard\/almabi$/);
});

test("dashboard keeps its visual baseline and uses local assets", async ({ page }) => {
  await expect(page.locator("body")).toContainText("Сводная информация");
  await page.locator("[data-file-menu-toggle]").click();
  await expect(page.locator("[data-file-menu-panel]")).toBeVisible();
  await expect(page).toHaveScreenshot("dashboard.png", { animations: "disabled" });
  expect(page.externalRequests).toEqual([]);
});

test("year period toggle groups summary columns and can switch back", async ({ page }) => {
  const monthBtn = page.locator("[data-table-period='month']");
  const quarterBtn = page.locator("[data-table-period='quarter']");
  const yearBtn = page.locator("[data-table-period='year']");
  const monthColumns = page.locator("#almabiSummaryHead th.col-month");

  await expect(yearBtn).toHaveText("Год");
  await expect(monthColumns).toHaveCount(12);

  await quarterBtn.click();
  await expect(monthColumns).toHaveCount(4);

  await yearBtn.click();
  await expect(monthColumns).toHaveCount(1);
  await expect(monthColumns.first()).toContainText("Год");

  await monthBtn.click();
  await expect(monthColumns).toHaveCount(12);

  const chartYearBtn = page.locator("[data-chart-period='year']");
  await page.locator("[data-tab-button='revenue']").click();
  await expect(chartYearBtn).toBeVisible();
  await chartYearBtn.click();
  await expect(page.locator("#almabiRevenueTrendChart")).toBeVisible();
});

test("charts and report pages remain operational", async ({ page }) => {
  await page.goto("/dashboard/almabi-charts");
  await expect(page.locator("body")).toContainText("Графики БДР");
  await expect(page).toHaveScreenshot("charts.png", { animations: "disabled" });

  await page.goto("/dashboard/almabi-revenue-report");
  await expect(page.locator("body")).toContainText("Отчёт по выручке");
  await expect(page).toHaveScreenshot("revenue-report.png", { animations: "disabled" });
  expect(page.externalRequests).toEqual([]);
});
