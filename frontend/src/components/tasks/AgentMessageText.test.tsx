import { screen, within } from "@testing-library/react";
import { describe, expect } from "vitest";
import { AgentMessageText } from "@/components/tasks/AgentMessageText";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const TABLE = "Итог:\n\n| Файл | Тестов |\n|:---|---:|\n| **`calc.py`** | 9 |";

describe("AgentMessageText", () => {
  test("ссылки в тексте, markdown и таблице кликабельны, код остаётся кодом", () => {
    renderWithProviders(<AgentMessageText text={'Ссылка https://example.com/a?q=1. [Jira](https://example.org/b) `https://example.net/code`\n\n| Сервис | Адрес |\n|---|---|\n| Оплата | https://example.com/pay |'} />);
    expect(screen.getByRole("link", { name: "https://example.com/a?q=1" })).toHaveAttribute("href", "https://example.com/a?q=1");
    expect(screen.getByRole("link", { name: "Jira" })).toHaveAttribute("href", "https://example.org/b");
    expect(screen.getByRole("link", { name: "https://example.com/pay" })).toHaveAttribute("target", "_blank");
    expect(screen.queryByRole("link", { name: "https://example.net/code" })).not.toBeInTheDocument();
  });
  test("таблица — с шапкой, ячейками и выравниванием колонок", () => {
    renderWithProviders(<AgentMessageText text={TABLE} />);

    const table = screen.getByRole("table");
    const headers = within(table).getAllByRole("columnheader");
    expect(headers.map((header) => header.textContent)).toEqual(["Файл", "Тестов"]);
    const cells = within(table).getAllByRole("cell");
    expect(cells.map((cell) => cell.textContent)).toEqual(["calc.py", "9"]);
    expect(cells[1]).toHaveClass("text-right");
    expect(headers[0]).toHaveClass("text-left");
  });

  test("код внутри жирного — без обратных кавычек", () => {
    renderWithProviders(<AgentMessageText text="Изменён **`calc.py`**" />);

    const code = screen.getByText("calc.py");
    expect(code.tagName).toBe("CODE");
    expect(code).toHaveClass("font-bold");
    expect(screen.queryByText(/`/)).toBeNull();
  });

  test("нумерованный список, разорванный блоками кода, продолжает нумерацию: у каждого <ol> свой start", () => {
    const text = [
      "Что нужно сделать:",
      "",
      "1. **Создать очередь**",
      "   ```python",
      "   queue = Queue()",
      "   ```",
      "2. **Добавить элемент**",
      "   - через `put()`",
      "3. **Взять элемент**",
    ].join("\n");
    const { container } = renderWithProviders(<AgentMessageText text={text} />);

    const starts = Array.from(container.querySelectorAll("ol")).map((list) => list.getAttribute("start"));
    expect(starts).toEqual(["1", "2", "3"]);
    expect(container.querySelectorAll("ul")).toHaveLength(1);
  });
});
