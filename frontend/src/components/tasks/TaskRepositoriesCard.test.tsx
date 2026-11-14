import { screen, within } from "@testing-library/react";
import { describe, expect } from "vitest";
import { TaskRepositoriesCard } from "@/components/tasks/TaskRepositoriesCard";
import { test } from "@/test/fixtures";
import { makeRepository, makeTask, makeTaskRepository } from "@/test/factories";
import { renderWithProviders } from "@/test/renderWithProviders";
import { TaskStatus, type Task } from "@/lib/types";

const EMPTY_TITLE = "Репозитории не привязаны";
const NOT_CLONED = "ещё не склонирован";

function renderCard(task: Partial<Task> = {}) {
  return renderWithProviders(<TaskRepositoriesCard task={makeTask({ id: "t1", ...task })} />);
}

describe("TaskRepositoriesCard", () => {
  test.for([
    { state: "загрузка", response: () => new Promise(() => {}), loading: true },
    { state: "пустой список", response: [], loading: false },
  ])("$state", async ({ response, loading }, { api }) => {
    api.respond("GET /tasks/t1/repositories", response);
    renderCard();

    if (loading) {
      expect(await screen.findByRole("status")).toHaveTextContent("Загрузка…");
      expect(screen.queryByText(EMPTY_TITLE)).not.toBeInTheDocument();
    } else {
      expect(await screen.findByText(EMPTY_TITLE)).toBeInTheDocument();
      expect(screen.queryByRole("status")).not.toBeInTheDocument();
    }
  });

  test.for([
    { status: TaskStatus.NEW, canAdd: true },
    { status: TaskStatus.IN_PROGRESS, canAdd: true },
    { status: TaskStatus.FAILED, canAdd: true },
    { status: TaskStatus.DONE, canAdd: false },
    { status: TaskStatus.ARCHIVED, canAdd: false },
  ])("$status: добавить — $canAdd", async ({ status, canAdd }, { api }) => {
    api.respond("GET /tasks/t1/repositories", []);
    renderCard({ status });

    await screen.findByText(EMPTY_TITLE);
    expect(Boolean(screen.queryByRole("button", { name: "Добавить" }))).toBe(canAdd);
  });

  test("диалог предлагает только не привязанные, роль по умолчанию — чтение", async ({ api }) => {
    api.respond("GET /tasks/t1/repositories", [makeTaskRepository({ repository_id: "r1" })]);
    api.respond("GET /repositories", [
      makeRepository({ id: "r1", name: "backend" }),
      makeRepository({ id: "r2", name: "frontend", default_branch: "develop" }),
    ]);
    api.respond("POST /tasks/t1/repositories", []);
    const { user } = renderCard({ status: TaskStatus.PAUSED });

    await user.click(await screen.findByRole("button", { name: "Добавить" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).queryByText("backend")).not.toBeInTheDocument();
    await user.click(within(dialog).getByRole("checkbox"));
    await user.click(within(dialog).getByRole("button", { name: "Добавить" }));

    expect(api.mutations()).toEqual([
      {
        method: "POST",
        path: "/tasks/t1/repositories",
        body: {
          repositories: [{ repository_id: "r2", role: "read_only", base_branch: "develop" }],
        },
      },
    ]);
  });

  test.for([
    { case: "до запуска, не склонирован", status: TaskStatus.NEW, cloned: false, chat: false, removable: true },
    { case: "в «Ошибке», не склонирован", status: TaskStatus.FAILED, cloned: false, chat: false, removable: true },
    { case: "уже склонирован", status: TaskStatus.NEW, cloned: true, chat: false, removable: false },
    { case: "идёт прогон", status: TaskStatus.PAUSED, cloned: false, chat: false, removable: false },
    { case: "идёт чат", status: TaskStatus.REFINING, cloned: false, chat: true, removable: false },
  ])("$case: убрать — $removable", async ({ status, cloned, chat, removable }, { api }) => {
    api.respond("GET /tasks/t1/repositories", [
      makeTaskRepository({ id: "tr1", repository_id: "r1", cloned_at: cloned ? "2026-11-14T10:00:00Z" : null }),
    ]);
    api.respond("GET /repositories", [makeRepository({ id: "r1", name: "backend" })]);
    renderCard({ status, chat_active: chat });

    await screen.findByText("backend");
    expect(Boolean(screen.queryByText(NOT_CLONED))).toBe(!cloned);
    expect(Boolean(screen.queryByRole("button", { name: "Удалить backend" }))).toBe(removable);
  });

  test("убрать несклонированный — после подтверждения", async ({ api }) => {
    api.respond("GET /tasks/t1/repositories", [
      makeTaskRepository({ id: "tr1", repository_id: "r1", cloned_at: null }),
    ]);
    api.respond("GET /repositories", [makeRepository({ id: "r1", name: "backend" })]);
    api.respond("DELETE /tasks/t1/repositories/tr1", null);
    const { user } = renderCard({ status: TaskStatus.NEW });

    await user.click(await screen.findByRole("button", { name: "Удалить backend" }));
    await user.click(await screen.findByRole("button", { name: "Удалить" }));

    expect(api.mutations()).toEqual([
      { method: "DELETE", path: "/tasks/t1/repositories/tr1", body: undefined },
    ]);
  });
});
