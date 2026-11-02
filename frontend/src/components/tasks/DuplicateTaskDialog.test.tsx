import { screen } from "@testing-library/react";
import { describe, expect, vi } from "vitest";
import { DuplicateTaskDialog } from "@/components/tasks/DuplicateTaskDialog";
import { makeTask } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

describe("DuplicateTaskDialog", () => {
  test.for([
    { error: { status: 409, code: "task_code_taken", message: "Задача с кодом RR-1 уже существует" }, underField: true },
    { error: { status: 409, code: "conflict", message: "Дублировать можно только выполненную задачу" }, underField: false },
  ])("ошибка «$error.code» под полем кода: $underField", async ({ error, underField }, { api, toasts }) => {
    api.respond("GET /tasks/t1/repositories", []);
    api.respond("POST /tasks/t1/duplicate", { error });
    const { user } = renderWithProviders(
      <DuplicateTaskDialog
        task={makeTask({ id: "t1", description: "Кнопка выгрузки в CSV" })}
        open
        onOpenChange={vi.fn()}
      />,
    );

    const field = await screen.findByLabelText("Код задачи");
    await user.type(field, "RR-1");
    await user.click(screen.getByRole("button", { name: "Создать копию" }));

    if (underField) {
      await vi.waitFor(() => expect(field).toHaveAccessibleDescription(new RegExp(error.message)));
      expect(toasts.error).not.toHaveBeenCalled();
    } else {
      await expect.poll(() => toasts.error.mock.calls).toEqual([[error.message]]);
      expect(field).not.toHaveAttribute("aria-invalid", "true");
    }
  });
});
