import { beforeEach, describe, expect, it } from "vitest";
import { createMemoryHistory } from "vue-router";
import WorkspaceLayout from "../../src/layouts/WorkspaceLayout.vue";
import { createAppRouter } from "../../src/router";
import { LANDING_SESSION_KEY } from "../../src/router/landingEntry";

function testRouter() {
  return createAppRouter(createMemoryHistory());
}

async function navigate(path: string) {
  const router = testRouter();
  await router.push(path);
  await router.isReady();
  return router;
}

beforeEach(() => {
  window.sessionStorage.clear();
});

describe("formal landing gate", () => {
  it("serves the accepted light landing at / without WorkspaceLayout", async () => {
    const router = await navigate("/");
    const route = router.currentRoute.value;

    expect(route.name).toBe("Landing");
    expect(route.matched).toHaveLength(1);
    // Landing route no longer passes static props (dark theme is set via CSS)
    expect(route.matched.some((record) => record.components?.default === WorkspaceLayout)).toBe(false);
    expect(window.sessionStorage.getItem(LANDING_SESSION_KEY)).toBeNull();

    window.sessionStorage.setItem(LANDING_SESSION_KEY, "1");
    const enteredRouter = await navigate("/");
    expect(enteredRouter.currentRoute.value.name).toBe("Landing");
  });

  it("gates a fresh /home session and preserves its full target", async () => {
    const router = await navigate("/home");

    expect(router.currentRoute.value.name).toBe("Landing");
    expect(router.currentRoute.value.query.next).toBe("/home");
  });

  it("preserves an Agent execution deep link including query and hash", async () => {
    const target = "/copilot?execution_id=abc#workflow";
    const router = await navigate(target);

    expect(router.currentRoute.value.name).toBe("Landing");
    expect(router.currentRoute.value.query.next).toBe(target);
  });

  it("allows business routes directly after entry, including across router instances", async () => {
    window.sessionStorage.setItem(LANDING_SESSION_KEY, "1");

    // /dashboard redirects to /home (which is under WorkspaceLayout)
    const homeRouter = await navigate("/home");
    expect(homeRouter.currentRoute.value.path).toBe("/home");
    expect(homeRouter.currentRoute.value.matched.some((r) => r.components?.default === WorkspaceLayout)).toBe(true);

    const copilotRouter = await navigate("/copilot?execution_id=abc");
    expect(copilotRouter.currentRoute.value.fullPath).toBe("/copilot?execution_id=abc");
  });

  it("routes removed preview URLs through the existing public 404 flow", async () => {
    for (const path of ["/landing-preview/dark", "/landing-preview/light"]) {
      const router = await navigate(path);
      expect(router.currentRoute.value.path).toBe("/404");
      expect(router.currentRoute.value.matched).toHaveLength(1);
      expect(router.currentRoute.value.matched.some((record) => record.components?.default === WorkspaceLayout)).toBe(false);
      expect(window.sessionStorage.getItem(LANDING_SESSION_KEY)).toBeNull();
    }
  });

  it("preserves the existing public 404 behavior without a gate loop", async () => {
    const router = await navigate("/route-that-does-not-exist");

    expect(router.currentRoute.value.path).toBe("/404");
    expect(window.sessionStorage.getItem(LANDING_SESSION_KEY)).toBeNull();
  });
});
