import { afterEach, describe, expect, it, vi } from "vitest";
import {
  SIDEBAR_COLLAPSE_BELOW,
  SIDEBAR_COMPACT_WIDTH,
  SIDEBAR_DEFAULT_WIDTH,
  SIDEBAR_MAX_WIDTH,
  isSidebarCompact,
  normalizeSidebarWidth,
  readStoredSidebarWidth,
  stepSidebarWidth,
  storeSidebarWidth,
} from "@/lib/sidebarWidth";

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("normalizeSidebarWidth", () => {
  it.each([
    { input: 0, expected: SIDEBAR_COMPACT_WIDTH },
    { input: SIDEBAR_COLLAPSE_BELOW - 1, expected: SIDEBAR_COMPACT_WIDTH },
    { input: SIDEBAR_COLLAPSE_BELOW, expected: SIDEBAR_COLLAPSE_BELOW },
    { input: 300.4, expected: 300 },
    { input: 9999, expected: SIDEBAR_MAX_WIDTH },
    { input: Number.NaN, expected: SIDEBAR_DEFAULT_WIDTH },
  ])("$input → $expected", ({ input, expected }) => {
    expect(normalizeSidebarWidth(input)).toBe(expected);
  });

  it("только схлопнутое меню — режим значков", () => {
    expect(isSidebarCompact(SIDEBAR_COMPACT_WIDTH)).toBe(true);
    expect(isSidebarCompact(SIDEBAR_COLLAPSE_BELOW)).toBe(false);
  });
});

describe("stepSidebarWidth", () => {
  it("из режима значков вправо — сразу до порога подписей, влево — остаётся", () => {
    expect(stepSidebarWidth(SIDEBAR_COMPACT_WIDTH, 1)).toBe(SIDEBAR_COLLAPSE_BELOW);
    expect(stepSidebarWidth(SIDEBAR_COMPACT_WIDTH, -1)).toBe(SIDEBAR_COMPACT_WIDTH);
  });

  it("шаг в обычном режиме, у порога меню схлопывается", () => {
    expect(stepSidebarWidth(248, 1)).toBe(264);
    expect(stepSidebarWidth(SIDEBAR_COLLAPSE_BELOW, -1)).toBe(SIDEBAR_COMPACT_WIDTH);
    expect(stepSidebarWidth(SIDEBAR_MAX_WIDTH, 1)).toBe(SIDEBAR_MAX_WIDTH);
  });
});

describe("хранение ширины", () => {
  it("читает сохранённую ширину", () => {
    storeSidebarWidth(300);
    expect(readStoredSidebarWidth()).toBe(300);
  });

  it("без записи и при мусоре — ширина по умолчанию", () => {
    expect(readStoredSidebarWidth()).toBe(SIDEBAR_DEFAULT_WIDTH);
    localStorage.setItem("tracker.sidebarWidth", "abc");
    expect(readStoredSidebarWidth()).toBe(SIDEBAR_DEFAULT_WIDTH);
  });

  it("недоступное хранилище не ломает чтение и запись", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(readStoredSidebarWidth()).toBe(SIDEBAR_DEFAULT_WIDTH);
    expect(() => storeSidebarWidth(300)).not.toThrow();
  });
});
