/**
 * Vitest global setup
 * Ensures browser APIs used by unit tests are available in jsdom environment.
 */

// Polyfill localStorage / sessionStorage if not available in this jsdom version
if (typeof window !== "undefined") {
  // Some jsdom builds expose Storage on window but don't initialize
  // window.localStorage / window.sessionStorage as proper objects.
  // Guard against this so tests calling .clear()/.getItem()/.setItem() don't throw.
  const makeStorage = (): Storage => {
    const store: Record<string, string> = {};
    return {
      get length() {
        return Object.keys(store).length;
      },
      clear() {
        for (const k of Object.keys(store)) delete store[k];
      },
      getItem(key: string) {
        return Object.prototype.hasOwnProperty.call(store, key) ? store[key]! : null;
      },
      setItem(key: string, value: string) {
        store[key] = String(value);
      },
      removeItem(key: string) {
        delete store[key];
      },
      key(index: number) {
        return Object.keys(store)[index] ?? null;
      },
    };
  };

  if (!window.localStorage) {
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: makeStorage(),
    });
  }

  if (!window.sessionStorage) {
    Object.defineProperty(window, "sessionStorage", {
      configurable: true,
      value: makeStorage(),
    });
  }
}
