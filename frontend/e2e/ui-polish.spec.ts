import { expect, test } from "@playwright/test";

test("品牌名称保持为 IndusOpt 工模智优", async ({ page }) => {
  await page.goto("/dashboard");
  await expect(page.locator(".logo-text")).toHaveText("IndusOpt 工模智优");
  await expect(page).toHaveTitle(/IndusOpt$/);
});

test("主页面越过上下边界后轻微回弹并复位", async ({ page }) => {
  await page.goto("/dashboard");
  const scroller = page.locator("[data-main-scroller]");

  const topPullStyle = await scroller.evaluate(async (element) => {
    element.scrollTop = 0;
    element.dispatchEvent(new WheelEvent("wheel", { deltaY: -100, bubbles: true }));
    await new Promise(requestAnimationFrame);
    return document.querySelector("[data-scroll-stage]")?.getAttribute("style");
  });
  expect(topPullStyle).toContain("translate3d(0px, 12px, 0px)");

  await page.waitForTimeout(420);
  await expect(page.locator("[data-scroll-stage]")).toHaveAttribute(
    "style",
    /translate3d\(0px, 0px, 0px\)/
  );

  const bottomPullStyle = await scroller.evaluate(async (element) => {
    element.scrollTop = element.scrollHeight;
    element.dispatchEvent(new WheelEvent("wheel", { deltaY: 100, bubbles: true }));
    await new Promise(requestAnimationFrame);
    return document.querySelector("[data-scroll-stage]")?.getAttribute("style");
  });
  expect(bottomPullStyle).toContain("translate3d(0px, -12px, 0px)");

  await page.waitForTimeout(420);
  await expect(page.locator("[data-scroll-stage]")).toHaveAttribute(
    "style",
    /translate3d\(0px, 0px, 0px\)/
  );
});
