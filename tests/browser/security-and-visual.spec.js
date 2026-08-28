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

test("charts and report pages remain operational", async ({ page }) => {
  await page.goto("/dashboard/almabi-charts");
  await expect(page.locator("body")).toContainText("Графики БДР");
  await expect(page).toHaveScreenshot("charts.png", { animations: "disabled" });

  await page.goto("/dashboard/almabi-revenue-report");
  await expect(page.locator("body")).toContainText("Отчёт по выручке");
  await expect(page).toHaveScreenshot("revenue-report.png", { animations: "disabled" });
  expect(page.externalRequests).toEqual([]);
});
