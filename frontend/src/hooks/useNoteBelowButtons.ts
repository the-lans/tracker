import { useLayoutEffect, useState, type RefObject } from "react";
import { noteBelowButtons } from "@/lib/headerLayout";

/** Атрибут элементов слева, чья ширина без обрезки нужна для расчёта (строка аккаунта; название не мешает). */
export const FIT_ATTRIBUTE = "data-fit";

/**
 * Раздел 15.2: надпись шапки задачи под кнопками (true) или под строкой аккаунта (false).
 * Пересчитывается при изменении размеров левого блока и группы кнопок. ``signal`` —
 * меняется вместе с текстом шапки (название, аккаунт, надпись).
 */
export function useNoteBelowButtons(
  left: RefObject<HTMLElement | null>,
  buttons: RefObject<HTMLElement | null>,
  measure: RefObject<HTMLElement | null>,
  signal: unknown,
): boolean {
  const [below, setBelow] = useState(false);

  useLayoutEffect(() => {
    const leftEl = left.current;
    const buttonsEl = buttons.current;
    const measureEl = measure.current;
    if (leftEl === null || buttonsEl === null || measureEl === null) return;

    const update = () => {
      const leftBox = leftEl.getBoundingClientRect();
      const buttonsBox = buttonsEl.getBoundingClientRect();
      const needed = Array.from(leftEl.querySelectorAll<HTMLElement>(`[${FIT_ATTRIBUTE}]`)).map(
        (element) => element.scrollWidth,
      );
      setBelow(
        noteBelowButtons({
          buttonsWrapped: buttonsBox.top >= leftBox.bottom - 1,
          leftNeeded: Math.max(0, ...needed),
          leftWidth: leftEl.clientWidth,
          noteWidth: measureEl.offsetWidth,
          buttonsWidth: buttonsBox.width,
        }),
      );
    };

    update();
    const observer = new ResizeObserver(update);
    observer.observe(leftEl);
    observer.observe(buttonsEl);
    return () => observer.disconnect();
  }, [left, buttons, measure, signal]);

  return below;
}
