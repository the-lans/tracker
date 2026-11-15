import { screen, within } from "@testing-library/react";
import { describe, expect } from "vitest";
import { LibraryPage } from "@/pages/LibraryPage";
import { makeNode } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const prompt = makeNode({ id: "l1", pipeline_id: null, is_library_item: true, name: "Ревью" });

describe("LibraryPage", () => {
  test.for([
    { query: "РЕВЬЮ", target: "Ревью" },
    { query: "/review", target: "Ревью" },
    { query: "безопасности", target: "Ревью" },
  ])("поиск «$query» находит промт", async ({ query, target }, { api }) => {
    api.respond("GET /nodes", [
      makeNode({ ...prompt, slash_name: "review", description: "Проверка безопасности" }),
      makeNode({ id: "l2", name: "Тестирование", is_library_item: true, pipeline_id: null }),
    ]);
    const { user } = renderWithProviders(<LibraryPage />);
    await screen.findByTitle("Ревью");
    await user.type(screen.getByRole("textbox", { name: "Поиск промтов" }), query);
    expect(screen.getByTitle(target)).toBeInTheDocument();
    expect(screen.queryByTitle("Тестирование")).not.toBeInTheDocument();
  });

  test("пустой результат поиска объясняется и сброс возвращает список", async ({ api }) => {
    api.respond("GET /nodes", [prompt]);
    const { user } = renderWithProviders(<LibraryPage />);
    await screen.findByTitle("Ревью");
    const search = screen.getByRole("textbox", { name: "Поиск промтов" });
    await user.type(search, "несуществующий промт");
    expect(screen.getByText("Промты не найдены")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Очистить поиск" }));
    expect(screen.getByTitle("Ревью")).toBeInTheDocument();
  });

  test.for([
    {
      response: { error: { status: 409, message: "Промт выполняют ноды пайплайнов — вместо удаления доступна архивация" } },
      shown: "Промт выполняют ноды пайплайнов — вместо удаления доступна архивация",
    },
    { response: { error: { status: 500, message: "Сбой сервера" } }, shown: "Сбой сервера" },
  ])("отказ в удалении → «$shown»", async ({ response, shown }, { api, toasts }) => {
    api.respond("GET /nodes", [prompt]);
    api.respond("DELETE /nodes/l1", response);
    const { user } = renderWithProviders(<LibraryPage />);

    await user.click(await screen.findByRole("button", { name: "Удалить Ревью" }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Удалить" }));

    await expect.poll(() => toasts.error.mock.calls).toEqual([[shown]]);
  });
});
