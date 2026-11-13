import { screen } from "@testing-library/react";
import { describe, expect, vi } from "vitest";
import { TaskCategoryForm } from "@/components/taskCategories/TaskCategoryForm";
import type { TaskCategory } from "@/lib/types";
import type { MockedApi } from "@/test/apiMock";
import { makeNode, makeTaskCategory } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

function renderForm(api: MockedApi, category?: TaskCategory) {
  api.respond("GET /pipelines", [
    { id: "p1", name: "Фича", is_archived: false, created_by: "u1" },
    { id: "p2", name: "Старый", is_archived: true, created_by: "u1" },
  ]);
  api.respond("GET /nodes", [
    makeNode({ id: "lib1", name: "Ревью", pipeline_id: null, is_library_item: true }),
    makeNode({ id: "lib2", name: "Устаревший", pipeline_id: null, is_library_item: true, is_archived: true }),
  ]);
  api.respond("POST /task-categories", makeTaskCategory());
  api.respond("PUT /task-categories/cat1", makeTaskCategory());
  const onSaved = vi.fn();
  return { ...renderWithProviders(<TaskCategoryForm category={category} onSaved={onSaved} onCancel={vi.fn()} />), onSaved };
}

function savedRequest(api: MockedApi) {
  return api.mutations().find((request) => request.path.startsWith("/task-categories"));
}

describe("TaskCategoryForm", () => {
  test("создание отправляет все настройки категории", async ({ api }) => {
    const { user, onSaved } = renderForm(api);

    await user.type(screen.getByLabelText("Название"), " Бэкенд ");
    await user.click(screen.getByRole("combobox", { name: "Пайплайн по умолчанию" }));
    await user.click(await screen.findByRole("option", { name: "Фича" }));
    await user.click(screen.getByRole("switch"));
    await user.click(await screen.findByRole("checkbox", { name: "Ревью" }));
    await user.clear(screen.getByLabelText("Приоритет (очередь)"));
    await user.type(screen.getByLabelText("Приоритет (очередь)"), "500");
    await user.click(screen.getByRole("checkbox", { name: "Занимать слот параллельного запуска задач" }));
    await user.click(screen.getByRole("button", { name: "Создать" }));

    expect(savedRequest(api)).toEqual({
      method: "POST",
      path: "/task-categories",
      body: {
        name: "Бэкенд",
        pipeline_id: "p1",
        auto_accept_plan: true,
        library_prompt_ids: ["lib1"],
        queue_priority: 500,
        occupies_slot: true,
      },
    });
    await vi.waitFor(() => expect(onSaved).toHaveBeenCalled());
  });

  test("архивные пайплайн и промт не предлагаются новой категории", async ({ api }) => {
    const { user } = renderForm(api);

    await screen.findByRole("checkbox", { name: "Ревью" });
    await user.click(screen.getByRole("combobox", { name: "Пайплайн по умолчанию" }));

    expect((await screen.findAllByRole("option")).map((option) => option.textContent)).toEqual([
      "Без пайплайна",
      "Фича",
    ]);
    expect(screen.queryByText(/Устаревший/)).not.toBeInTheDocument();
  });

  test("уже выбранные архивные остаются у категории", async ({ api }) => {
    renderForm(api, makeTaskCategory({ pipeline_id: "p2", library_prompt_ids: ["lib2"] }));

    expect(await screen.findByRole("checkbox", { name: "Устаревший (в архиве)" })).toBeChecked();
    expect(screen.getByRole("combobox", { name: "Пайплайн по умолчанию" })).toHaveTextContent(
      "Старый (в архиве)",
    );
  });

  test.for(["0", "1000001", "1.5", ""])("приоритет «%s» не сохраняется", async (priority, { api }) => {
    const { user } = renderForm(api);
    await user.type(screen.getByLabelText("Название"), "Бэкенд");

    await user.clear(screen.getByLabelText("Приоритет (очередь)"));
    if (priority) await user.type(screen.getByLabelText("Приоритет (очередь)"), priority);

    expect(screen.getByRole("button", { name: "Создать" })).toBeDisabled();
    expect(screen.getByLabelText("Приоритет (очередь)")).toHaveAttribute("aria-invalid", "true");
  });

  test.for(["", "   "])("название «%s» не сохраняется", async (name, { api }) => {
    const { user } = renderForm(api);

    if (name) await user.type(screen.getByLabelText("Название"), name);

    expect(screen.getByRole("button", { name: "Создать" })).toBeDisabled();
  });

  test.for([
    { field: "Название", required: true },
    { field: "Пайплайн по умолчанию", required: false },
    { field: "Приоритет (очередь)", required: false },
  ])("«$field» — обязательное: $required", ({ field, required }, { api }) => {
    renderForm(api);

    expect(screen.getByText(field, { selector: "label" }).hasAttribute("data-required")).toBe(required);
  });

  test("правка сохраняет категорию целиком", async ({ api }) => {
    const { user } = renderForm(api, makeTaskCategory({ queue_priority: 300 }));

    await user.clear(screen.getByLabelText("Название"));
    await user.type(screen.getByLabelText("Название"), "Фронтенд");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(savedRequest(api)).toMatchObject({
      method: "PUT",
      path: "/task-categories/cat1",
      body: { name: "Фронтенд", pipeline_id: null, queue_priority: 300 },
    });
  });
});
