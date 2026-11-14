import { screen } from "@testing-library/react";
import { describe, expect, vi } from "vitest";
import { FilterSelect } from "@/components/common/filters/FilterSelect";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

type Color = "red" | "blue";
const LABELS: Record<Color, string> = { red: "Красный", blue: "Синий" };

function renderFilter(value: Color | undefined) {
  const onChange = vi.fn();
  const view = renderWithProviders(
    <FilterSelect
      value={value}
      onChange={onChange}
      values={["blue", "red"]}
      labels={LABELS}
      allLabel="Все цвета"
      label="Цвет"
    />,
  );
  return { ...view, onChange };
}

describe("FilterSelect", () => {
  test.for([
    { value: undefined, shown: "Все цвета" },
    { value: "red" as const, shown: "Красный" },
  ])("значение $value → «$shown»", ({ value, shown }) => {
    renderFilter(value);

    const trigger = screen.getByRole("combobox", { name: "Цвет" });
    expect(trigger).toHaveTextContent(shown);
    // Обрезанная в поле подпись целиком видна в подсказке.
    expect(trigger).toHaveAttribute("title", shown);
  });

  test("пункты — «Все …», затем значения в заданном порядке", async () => {
    const { user } = renderFilter(undefined);

    await user.click(screen.getByRole("combobox", { name: "Цвет" }));

    expect(screen.getAllByRole("option").map((option) => option.textContent)).toEqual([
      "Все цвета",
      "Синий",
      "Красный",
    ]);
  });

  test.for([
    { from: undefined, pick: "Синий", expected: "blue" },
    { from: "red" as const, pick: "Все цвета", expected: undefined },
  ])("выбор «$pick» → $expected", async ({ from, pick, expected }) => {
    const { user, onChange } = renderFilter(from);

    await user.click(screen.getByRole("combobox", { name: "Цвет" }));
    await user.click(screen.getByRole("option", { name: pick }));

    expect(onChange).toHaveBeenCalledWith(expected);
  });
});
