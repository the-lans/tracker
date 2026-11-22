import { act } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { useSidebarWidth } from "@/hooks/useSidebarWidth";
import {
  SIDEBAR_COMPACT_WIDTH,
  SIDEBAR_DEFAULT_WIDTH,
  SIDEBAR_MAX_WIDTH,
} from "@/lib/sidebarWidth";
import { renderHookWithClient } from "@/test/renderWithProviders";

const STORAGE_KEY = "tracker.sidebarWidth";

afterEach(() => localStorage.clear());

describe("useSidebarWidth", () => {
  it("без сохранённого значения — ширина по умолчанию, меню с подписями", () => {
    const { result } = renderHookWithClient(() => useSidebarWidth());

    expect(result.current.width).toBe(SIDEBAR_DEFAULT_WIDTH);
    expect(result.current.compact).toBe(false);
  });

  it("берёт ширину, сохранённую в прошлый раз", () => {
    localStorage.setItem(STORAGE_KEY, "300");

    const { result } = renderHookWithClient(() => useSidebarWidth());

    expect(result.current.width).toBe(300);
  });

  it("ширину приводит к допустимой и сохраняет", () => {
    const { result } = renderHookWithClient(() => useSidebarWidth());

    act(() => result.current.setWidth(9999));
    expect(result.current.width).toBe(SIDEBAR_MAX_WIDTH);
    expect(localStorage.getItem(STORAGE_KEY)).toBe(String(SIDEBAR_MAX_WIDTH));

    act(() => result.current.setWidth(120));
    expect(result.current.width).toBe(SIDEBAR_COMPACT_WIDTH);
    expect(result.current.compact).toBe(true);
    expect(localStorage.getItem(STORAGE_KEY)).toBe(String(SIDEBAR_COMPACT_WIDTH));
  });

  it("сброс возвращает ширину по умолчанию", () => {
    const { result } = renderHookWithClient(() => useSidebarWidth());
    act(() => result.current.setWidth(380));

    act(() => result.current.reset());

    expect(result.current.width).toBe(SIDEBAR_DEFAULT_WIDTH);
    expect(localStorage.getItem(STORAGE_KEY)).toBe(String(SIDEBAR_DEFAULT_WIDTH));
  });
});
