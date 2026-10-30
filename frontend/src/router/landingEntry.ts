import type { Router } from "vue-router";

export const LANDING_SESSION_KEY = "indusopt.landing.entered";
export const DEFAULT_LANDING_TARGET = "/home";


export function hasEnteredLanding() {
  return window.sessionStorage.getItem(LANDING_SESSION_KEY) === "1";
}

export function markLandingEntered() {
  window.sessionStorage.setItem(LANDING_SESSION_KEY, "1");
}

export function resolveLandingTarget(router: Router, next: unknown) {
  if (
    typeof next !== "string" ||
    !next.startsWith("/") ||
    next.startsWith("//") ||
    next.startsWith("/\\")
  ) {
    return DEFAULT_LANDING_TARGET;
  }

  try {
    const resolved = router.resolve(next);
    return resolved.matched.length > 0 ? resolved.fullPath : DEFAULT_LANDING_TARGET;
  } catch {
    return DEFAULT_LANDING_TARGET;
  }
}

export function enterFromLanding(router: Router, next: unknown) {
  const target = resolveLandingTarget(router, next);
  markLandingEntered();
  return router.replace(target);
}
