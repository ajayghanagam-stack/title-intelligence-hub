import { test, expect } from "@playwright/test";

/**
 * E2E tests for flag review removal from severity tabs.
 *
 * Prerequisites:
 *   - Backend running at localhost:8000
 *   - Frontend running at localhost:3000
 *   - Customer account admin@societytitle.com / admin123 with TI subscription
 *   - At least one completed pack with ≥2 open flags
 *
 * Verifies:
 *   1. Approving a flag removes it from the severity tab and decrements the count
 *   2. Rejecting a flag removes it from the severity tab and decrements the count
 *   3. The "All" tab count also decrements after review
 */

const CUSTOMER_EMAIL = "admin@societytitle.com";
const CUSTOMER_PASSWORD = "admin123";
const API_URL = "http://localhost:8000";
const NAV_TIMEOUT = 30_000;

test.describe.configure({ mode: "serial" });

async function loginViaApi(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.waitForLoadState("domcontentloaded");

  const loginResult = await page.evaluate(
    async ({ apiUrl, email, password }) => {
      const res = await fetch(`${apiUrl}/api/v1/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (!res.ok) {
        return { ok: false as const, status: res.status, error: await res.text() };
      }
      const data = await res.json();
      return { ok: true as const, data };
    },
    { apiUrl: API_URL, email: CUSTOMER_EMAIL, password: CUSTOMER_PASSWORD }
  );

  if (!loginResult.ok) {
    throw new Error(`Login API failed (${loginResult.status}): ${loginResult.error}`);
  }

  const { data } = loginResult;
  await page.evaluate(
    ({ token, org }) => {
      localStorage.setItem("auth_token", token);
      localStorage.setItem(
        "org-store",
        JSON.stringify({
          state: { currentOrgId: org.id, currentOrgName: org.name },
          version: 0,
        })
      );
      document.cookie = "has_session=1; path=/; SameSite=Lax";
    },
    { token: data.access_token, org: data.orgs[0] }
  );
}

async function navigateToFlags(page: import("@playwright/test").Page) {
  const packId = await page.evaluate(async (apiUrl: string) => {
    const token = localStorage.getItem("auth_token");
    const orgStore = JSON.parse(localStorage.getItem("org-store") || "{}");
    const orgId = orgStore.state?.currentOrgId;
    const res = await fetch(`${apiUrl}/api/v1/apps/title-intelligence/packs`, {
      headers: {
        Authorization: `Bearer ${token}`,
        "X-Org-Id": orgId,
      },
    });
    const packs = await res.json();
    const completed = (packs as { id: string; status: string }[]).find(
      (p) => p.status === "completed"
    );
    return completed?.id || null;
  }, API_URL);

  if (!packId) {
    throw new Error("No completed pack found for testing");
  }

  await page.goto(`/apps/title-intelligence/packs/${packId}/results`);
  await page.waitForFunction(
    () => !document.body.innerText.trim().startsWith("Loading"),
    { timeout: NAV_TIMEOUT }
  );
  await page.waitForLoadState("networkidle", { timeout: NAV_TIMEOUT });
}

/** Parse the count number from a tab button like "All (12)" or "Critical (3)" */
function parseTabCount(text: string | null): number {
  if (!text) return -1;
  const match = text.match(/\((\d+)\)/);
  return match ? parseInt(match[1], 10) : -1;
}

test.describe("Flag Review Removal", () => {
  test.beforeEach(async ({ page }) => {
    await loginViaApi(page);
  });

  test("approving a flag removes it from the list and decrements counts", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await navigateToFlags(page);

    // Read the "All" tab count before review
    const allTab = page.locator("button").filter({ hasText: /^All\s*\(/ });
    await expect(allTab).toBeVisible({ timeout: 10_000 });
    const allTextBefore = await allTab.textContent();
    const allCountBefore = parseTabCount(allTextBefore);

    if (allCountBefore < 1) {
      test.skip(true, "No open flags available for testing");
      return;
    }

    // Count visible flag rows before review
    const flagRows = page.locator("[class*='cursor-pointer']");
    const rowCountBefore = await flagRows.count();

    // Expand first flag row
    await flagRows.first().click();
    await page.waitForTimeout(500);

    // Check if the flag is open (has approve button)
    const approveBtn = page.locator("button").filter({ hasText: /^Approve$/ }).first();
    if (!(await approveBtn.isVisible({ timeout: 3_000 }).catch(() => false))) {
      test.skip(true, "First flag is not open — cannot test approval");
      return;
    }

    // Click Approve
    await approveBtn.click();

    // Wait for network refresh
    await page.waitForLoadState("networkidle", { timeout: 10_000 });
    // Small extra wait for React state update
    await page.waitForTimeout(1_000);

    // The "All" tab count should have decremented
    const allTextAfter = await allTab.textContent();
    const allCountAfter = parseTabCount(allTextAfter);
    expect(allCountAfter).toBe(allCountBefore - 1);

    // With pagination, row count may stay at PAGE_SIZE if more flags exist.
    // Verify the row count is at most what it was before (never increases).
    const rowCountAfter = await flagRows.count();
    expect(rowCountAfter).toBeLessThanOrEqual(rowCountBefore);

    // Verify no error toast
    const errorToast = page.locator("text=Failed to submit review");
    await expect(errorToast).not.toBeVisible({ timeout: 2_000 });
  });

  test("rejecting a flag removes it from the list and decrements counts", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await navigateToFlags(page);

    // Read the "All" tab count before review
    const allTab = page.locator("button").filter({ hasText: /^All\s*\(/ });
    await expect(allTab).toBeVisible({ timeout: 10_000 });
    const allTextBefore = await allTab.textContent();
    const allCountBefore = parseTabCount(allTextBefore);

    if (allCountBefore < 1) {
      test.skip(true, "No open flags available for testing");
      return;
    }

    // Expand first flag row
    const flagRows = page.locator("[class*='cursor-pointer']");
    await flagRows.first().click();
    await page.waitForTimeout(500);

    // Check if the flag is open (has reject button)
    const rejectBtn = page.locator("button").filter({ hasText: /^Reject$/ }).first();
    if (!(await rejectBtn.isVisible({ timeout: 3_000 }).catch(() => false))) {
      test.skip(true, "First flag is not open — cannot test rejection");
      return;
    }

    // Click Reject
    await rejectBtn.click();

    // Wait for network refresh
    await page.waitForLoadState("networkidle", { timeout: 10_000 });
    await page.waitForTimeout(1_000);

    // The "All" tab count should have decremented
    const allTextAfter = await allTab.textContent();
    const allCountAfter = parseTabCount(allTextAfter);
    expect(allCountAfter).toBe(allCountBefore - 1);

    // Verify no error toast
    const errorToast = page.locator("text=Failed to submit review");
    await expect(errorToast).not.toBeVisible({ timeout: 2_000 });
  });

  test("severity tab count decrements when its flag is reviewed", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await navigateToFlags(page);

    // Wait for tabs
    const allTab = page.locator("button").filter({ hasText: /^All\s*\(/ });
    await expect(allTab).toBeVisible({ timeout: 10_000 });

    // Find a severity tab with count > 0 (try Critical, then Warning, then Review)
    const severityTabs = [
      { key: "Critical", selector: page.locator("button").filter({ hasText: /^Critical\s*\(/ }) },
      { key: "Warning", selector: page.locator("button").filter({ hasText: /^Warning\s*\(/ }) },
      { key: "Review", selector: page.locator("button").filter({ hasText: /^Review\s*\(/ }) },
    ];

    let targetTab: typeof severityTabs[0] | null = null;
    let tabCountBefore = 0;

    for (const tab of severityTabs) {
      if (await tab.selector.isVisible().catch(() => false)) {
        const text = await tab.selector.textContent();
        const count = parseTabCount(text);
        if (count > 0) {
          targetTab = tab;
          tabCountBefore = count;
          break;
        }
      }
    }

    if (!targetTab) {
      test.skip(true, "No severity tab with open flags");
      return;
    }

    // Click the severity tab to filter
    await targetTab.selector.click();
    await page.waitForLoadState("networkidle", { timeout: 10_000 });

    // Expand first flag and approve
    const flagRows = page.locator("[class*='cursor-pointer']");
    const rowCountBefore = await flagRows.count();

    if (rowCountBefore < 1) {
      test.skip(true, "No flags visible in severity tab");
      return;
    }

    await flagRows.first().click();
    await page.waitForTimeout(500);

    const approveBtn = page.locator("button").filter({ hasText: /^Approve$/ }).first();
    if (!(await approveBtn.isVisible({ timeout: 3_000 }).catch(() => false))) {
      test.skip(true, "First flag is not open");
      return;
    }

    await approveBtn.click();
    await page.waitForLoadState("networkidle", { timeout: 10_000 });
    await page.waitForTimeout(1_000);

    // The specific severity tab count should have decremented
    const tabTextAfter = await targetTab.selector.textContent();
    const tabCountAfter = parseTabCount(tabTextAfter);
    expect(tabCountAfter).toBe(tabCountBefore - 1);
  });
});
