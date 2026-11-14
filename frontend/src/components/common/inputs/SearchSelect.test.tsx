import { screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, vi } from "vitest";
import { SEARCH_SELECT_LIMIT, SearchSelect } from "@/components/common/inputs/SearchSelect";
import type { SearchSelectOption } from "@/components/common/inputs/searchSelect.types";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const tasks: SearchSelectOption[] = [
  { value: "t1", label: "RR-100 · Каталог товаров" },
  { value: "t2", label: "RR-200 · Корзина" },
  { value: "t3", label: "OPS-7 · Отчёт по продажам" },
];

function renderSelect(options: readonly SearchSelectOption[] = tasks, initial: string | null = null) {
  const onChange = vi.fn();
  function Harness() {
    const [value, setValue] = useState(initial);
    return (
      <>
        <label htmlFor="parent">Родитель</label>
        <SearchSelect
          id="parent"
          value={value}
          options={options}
          clearLabel="Без родителя"
          onChange={(next) => {
            onChange(next);
            setValue(next);
          }}
        />
      </>
    );
  }
  const view = renderWithProviders(<Harness />);
  return { ...view, onChange, input: screen.getByRole("combobox", { name: "Родитель" }) };
}

const optionNames = () => screen.getAllByRole("option").map((option) => option.textContent);

describe("SearchSelect", () => {
  test.for([
    { query: "rr-", shown: ["RR-100 · Каталог товаров", "RR-200 · Корзина"] },
    { query: "корз", shown: ["RR-200 · Корзина"] },
    { query: "  отчёт ", shown: ["OPS-7 · Отчёт по продажам"] },
    { query: "нет такой", shown: [] },
  ])("«$query» → $shown", async ({ query, shown }) => {
    const { user, input } = renderSelect();

    await user.type(input, query);

    expect(optionNames()).toEqual(["Без родителя", ...shown]);
    expect(screen.queryByText("Ничего не найдено") !== null).toBe(shown.length === 0);
  });

  test("клик по варианту выбирает его и показывает в поле", async () => {
    const { user, input, onChange } = renderSelect();

    await user.type(input, "корз");
    await user.click(screen.getByRole("option", { name: "RR-200 · Корзина" }));

    expect(onChange).toHaveBeenCalledExactlyOnceWith("t2");
    expect(input).toHaveValue("RR-200 · Корзина");
    expect(input).toHaveFocus();
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  test("стрелки и Enter выбирают с клавиатуры", async () => {
    const { user, input, onChange } = renderSelect();

    await user.type(input, "rr");
    await user.keyboard("{ArrowDown}{ArrowDown}{Enter}");

    expect(onChange).toHaveBeenCalledExactlyOnceWith("t2");
  });

  test("наведённый мышью пункт выбирается по Enter", async () => {
    const { user, input, onChange } = renderSelect();

    await user.click(input);
    await user.hover(screen.getByRole("option", { name: "OPS-7 · Отчёт по продажам" }));
    await user.keyboard("{Enter}");

    expect(onChange).toHaveBeenCalledExactlyOnceWith("t3");
  });

  test("стрелка вверх с первого пункта уходит на последний", async () => {
    const { user, input, onChange } = renderSelect();

    await user.click(input);
    await user.keyboard("{ArrowUp}{Enter}");

    expect(onChange).toHaveBeenCalledExactlyOnceWith("t3");
  });

  test("«Без родителя» снимает выбор", async () => {
    const { user, input, onChange } = renderSelect(tasks, "t1");

    expect(input).toHaveValue("RR-100 · Каталог товаров");
    await user.click(input);
    await user.click(screen.getByRole("option", { name: "Без родителя" }));

    expect(onChange).toHaveBeenCalledExactlyOnceWith(null);
    expect(input).toHaveValue("Без родителя");
  });

  test("Escape закрывает список и возвращает выбранное", async () => {
    const { user, input, onChange } = renderSelect(tasks, "t1");

    await user.type(input, "корз");
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(input).toHaveValue("RR-100 · Каталог товаров");
    expect(onChange).not.toHaveBeenCalled();
  });

  test("длинный список обрезается с подсказкой уточнить поиск", async () => {
    const many = Array.from({ length: SEARCH_SELECT_LIMIT + 5 }, (_, index) => ({
      value: `t${index}`,
      label: `RR-${index} · Задача`,
    }));
    const { user, input } = renderSelect(many);

    await user.click(input);

    expect(screen.getAllByRole("option")).toHaveLength(SEARCH_SELECT_LIMIT + 1);
    expect(
      screen.getByText(`Показаны первые ${SEARCH_SELECT_LIMIT} из ${SEARCH_SELECT_LIMIT + 5} — уточните поиск`),
    ).toBeInTheDocument();
  });
});
