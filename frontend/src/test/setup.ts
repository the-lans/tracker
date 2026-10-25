import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// jsdom не реализует API, на которые опираются примитивы Radix (чекбокс
// меряет себя ResizeObserver'ом, Select работает с захватом указателя).
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= ResizeObserverStub;
Element.prototype.hasPointerCapture ??= () => false;
Element.prototype.releasePointerCapture ??= () => {};
Element.prototype.scrollIntoView ??= () => {};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
