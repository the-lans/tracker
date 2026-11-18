import { screen } from "@testing-library/react";
import { describe, expect } from "vitest";
import { TaskDetailsButton } from "@/components/tasks/TaskDetailsButton";
import { makeTask } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const OPEN_LABEL =
  "Открыть название, описание, ссылки и артефакты в отдельном окне";

describe("TaskDetailsButton", () => {
  test("кнопка открывает окно, крестик закрывает", async ({ api }) => {
    api.respond("GET /tasks/t1/artifacts", []);
    const { user } = renderWithProviders(
      <TaskDetailsButton
        task={makeTask({ id: "t1", title: "Профиль игрока" })}
      />,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: OPEN_LABEL }));
    expect(
      await screen.findByRole("dialog", { name: "Профиль игрока" }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Закрыть" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
