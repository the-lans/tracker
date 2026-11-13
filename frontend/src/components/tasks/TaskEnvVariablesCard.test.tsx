import { screen } from "@testing-library/react";
import { describe, expect } from "vitest";
import { TaskEnvVariablesCard } from "@/components/tasks/TaskEnvVariablesCard";
import { TaskStatus } from "@/lib/types";
import { makeTask } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const EMPTY_TITLE = "Переменных задачи нет";

describe("TaskEnvVariablesCard", () => {
  test.for([
    { state: "загрузка", response: () => new Promise(() => {}), loading: true },
    { state: "пустой список", response: [], loading: false },
  ])("$state", async (
    { response, loading },
    { api },
  ) => {
    api.respond("GET /tasks/t1/env-variables", response);
    renderWithProviders(<TaskEnvVariablesCard task={makeTask({ id: "t1" })} />);

    if (loading) {
      expect(await screen.findByRole("status")).toHaveTextContent("Загрузка…");
      expect(screen.queryByText(EMPTY_TITLE)).not.toBeInTheDocument();
    } else {
      expect(await screen.findByText(EMPTY_TITLE)).toBeInTheDocument();
      expect(screen.queryByRole("status")).not.toBeInTheDocument();
    }
  });

  test.for([
    { status: TaskStatus.IN_PROGRESS, editable: true },
    { status: TaskStatus.DONE, editable: false },
    { status: TaskStatus.ARCHIVED, editable: false },
  ])("$status — добавление переменной: $editable", async ({ status, editable }, { api }) => {
    api.respond("GET /tasks/t1/env-variables", []);
    renderWithProviders(<TaskEnvVariablesCard task={makeTask({ id: "t1", status })} />);

    await screen.findByText(EMPTY_TITLE);
    expect(screen.queryByRole("textbox", { name: "Ключ переменной" }) !== null).toBe(editable);
  });
});
