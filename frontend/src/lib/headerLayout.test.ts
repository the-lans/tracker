import { describe, expect, test } from "vitest";
import { NOTE_GAP_PX, noteBelowButtons } from "@/lib/headerLayout";

const base = {
  buttonsWrapped: false,
  leftNeeded: 400,
  leftWidth: 900,
  noteWidth: 230,
  buttonsWidth: 280,
};

describe("noteBelowButtons", () => {
  test("места хватает — надпись под кнопками", () => {
    expect(noteBelowButtons(base)).toBe(true);
  });

  test("кнопки ушли под название — надпись под аккаунтом", () => {
    expect(noteBelowButtons({ ...base, buttonsWrapped: true })).toBe(false);
  });

  test("слева начинается обрезка — надпись под аккаунтом", () => {
    expect(noteBelowButtons({ ...base, leftNeeded: 1000 })).toBe(false);
  });

  test("граница: слева ровно остаётся зазор", () => {
    expect(
      noteBelowButtons({ ...base, leftNeeded: base.leftWidth - NOTE_GAP_PX }),
    ).toBe(true);
    expect(
      noteBelowButtons({
        ...base,
        leftNeeded: base.leftWidth - NOTE_GAP_PX + 1,
      }),
    ).toBe(false);
  });

  test("надпись шире кнопок выступает влево и сдвигает границу", () => {
    const wide = { ...base, noteWidth: 380, buttonsWidth: 280 };

    expect(
      noteBelowButtons({
        ...wide,
        leftNeeded: base.leftWidth - NOTE_GAP_PX - 100,
      }),
    ).toBe(true);
    expect(
      noteBelowButtons({
        ...wide,
        leftNeeded: base.leftWidth - NOTE_GAP_PX - 99,
      }),
    ).toBe(false);
  });
});
