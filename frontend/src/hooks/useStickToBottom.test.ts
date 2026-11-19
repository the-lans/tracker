import { act, renderHook } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import { NEAR_BOTTOM_PX, useStickToBottom } from "@/hooks/useStickToBottom";

const SCROLL_HEIGHT = 2000;
const CLIENT_HEIGHT = 600;

/** Лента с заданным расстоянием до конца: jsdom сам размеров не считает. */
function setup() {
  const feed = document.createElement("div");
  const metrics = { scrollTop: SCROLL_HEIGHT - CLIENT_HEIGHT };
  Object.defineProperties(feed, {
    scrollHeight: { get: () => SCROLL_HEIGHT },
    clientHeight: { get: () => CLIENT_HEIGHT },
    scrollTop: { get: () => metrics.scrollTop },
  });
  const scrollTo = vi.fn();
  feed.scrollTo = scrollTo as unknown as typeof feed.scrollTo;

  const view = renderHook(
    ({ signal }) => useStickToBottom<HTMLDivElement>(signal),
    {
      initialProps: { signal: 0 },
    },
  );
  (view.result.current.ref as { current: HTMLDivElement | null }).current =
    feed;

  return {
    scrollTo,
    /** Пользователь остановился в `distance` px от конца ленты. */
    stopAt(distance: number) {
      metrics.scrollTop = SCROLL_HEIGHT - CLIENT_HEIGHT - distance;
      view.result.current.onScroll();
    },
    grow(signal: number) {
      view.rerender({ signal });
    },
    get hasUnseen() {
      return view.result.current.hasUnseen;
    },
    scrollToBottom() {
      act(() => view.result.current.scrollToBottom());
    },
  };
}

describe("useStickToBottom", () => {
  test("лента открыта у конца — следует за новым содержимым", () => {
    const feed = setup();

    feed.grow(1);

    expect(feed.scrollTo).toHaveBeenCalledWith({ top: SCROLL_HEIGHT });
  });

  test("пользователь у конца (в пределах порога) — лента следует", () => {
    const feed = setup();
    feed.stopAt(NEAR_BOTTOM_PX);

    feed.grow(1);

    expect(feed.scrollTo).toHaveBeenCalledTimes(1);
  });

  test("пролистал выше порога — лента стоит на месте", () => {
    const feed = setup();
    feed.stopAt(NEAR_BOTTOM_PX + 1);

    feed.grow(1);
    feed.grow(2);

    expect(feed.scrollTo).not.toHaveBeenCalled();
  });

  test("вернулся к концу — лента снова следует", () => {
    const feed = setup();
    feed.stopAt(500);
    feed.grow(1);
    feed.stopAt(40);

    feed.grow(2);

    expect(feed.scrollTo).toHaveBeenCalledTimes(1);
  });

  test("содержимое не менялось — лента не прокручивается", () => {
    const feed = setup();

    feed.grow(0);

    expect(feed.scrollTo).not.toHaveBeenCalled();
  });

  describe("подсказка о новом", () => {
    test("у конца её нет", () => {
      const feed = setup();

      feed.grow(1);

      expect(feed.hasUnseen).toBe(false);
    });

    test("пролистал вверх, содержимое выросло — подсказка появляется", () => {
      const feed = setup();
      feed.stopAt(500);

      feed.grow(1);

      expect(feed.hasUnseen).toBe(true);
    });

    test("вернулся к концу вручную — подсказка уходит", () => {
      const feed = setup();
      feed.stopAt(500);
      feed.grow(1);

      act(() => feed.stopAt(20));

      expect(feed.hasUnseen).toBe(false);
    });

    test("кнопка прокручивает к концу, подсказка уходит, лента следует снова", () => {
      const feed = setup();
      feed.stopAt(500);
      feed.grow(1);

      feed.scrollToBottom();
      feed.grow(2);

      expect(feed.scrollTo).toHaveBeenCalledWith({ top: SCROLL_HEIGHT });
      expect(feed.scrollTo).toHaveBeenCalledTimes(2);
      expect(feed.hasUnseen).toBe(false);
    });
  });
});
