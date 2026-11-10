import { screen } from "@testing-library/react";
import { describe, expect, vi } from "vitest";
import { TaskStartAccountCard } from "@/components/tasks/TaskStartAccountCard";
import { LlmAccountStatus, TaskStatus, type Task } from "@/lib/types";
import type { MockedApi } from "@/test/apiMock";
import { makeLlmAccount, makeTask } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const accounts = [
  makeLlmAccount({ id: "a1", label: "Claude — основной" }),
  makeLlmAccount({ id: "a2", label: "Codex — запасной", switch_order: 1 }),
  makeLlmAccount({
    id: "a3",
    label: "Выключенный",
    switch_order: 2,
    status: LlmAccountStatus.DISABLED,
  }),
  makeLlmAccount({ id: "a4", label: "Чужой", created_by: "u2" }),
];

function renderCard(api: MockedApi, task: Partial<Task>) {
  api.respond("GET /llm-accounts", accounts);
  const onUpdate = vi.fn();
  return {
    onUpdate,
    ...renderWithProviders(
      <TaskStartAccountCard task={makeTask(task)} pending={false} onUpdate={onUpdate} />,
    ),
  };
}

function trigger() {
  return screen.getByRole("combobox", { name: "Стартовый LLM-аккаунт" });
}

describe("TaskStartAccountCard", () => {
  test("в новой задаче — активные аккаунты автора и смена аккаунта", async ({ api }) => {
    const { user, onUpdate } = renderCard(api, { llm_account_id: "a1" });

    await vi.waitFor(() => expect(trigger()).toHaveTextContent("Claude — основной"));
    await user.click(trigger());
    const options = await screen.findAllByRole("option");
    expect(options.map((option) => option.textContent)).toEqual([
      "Автоматически",
      "Claude — основной",
      "Codex — запасной",
    ]);
    await user.click(screen.getByRole("option", { name: "Codex — запасной" }));

    expect(onUpdate).toHaveBeenCalledWith({ llm_account_id: "a2" });
  });

  test("без стартового аккаунта — «Автоматически»", async ({ api }) => {
    const { user, onUpdate } = renderCard(api, { llm_account_id: null });

    await vi.waitFor(() => expect(trigger()).toHaveTextContent("Автоматически"));
    await user.click(trigger());
    await user.click(await screen.findByRole("option", { name: "Claude — основной" }));

    expect(onUpdate).toHaveBeenCalledWith({ llm_account_id: "a1" });
  });

  test("«Автоматически» сбрасывает стартовый аккаунт", async ({ api }) => {
    const { user, onUpdate } = renderCard(api, { llm_account_id: "a1" });

    await vi.waitFor(() => expect(trigger()).toHaveTextContent("Claude — основной"));
    await user.click(trigger());
    await user.click(await screen.findByRole("option", { name: "Автоматически" }));

    expect(onUpdate).toHaveBeenCalledWith({ llm_account_id: null });
  });

  test("выключенный стартовый аккаунт остаётся выбранным", async ({ api }) => {
    const { user } = renderCard(api, { llm_account_id: "a3" });

    await vi.waitFor(() => expect(trigger()).toHaveTextContent("Выключенный"));
    await user.click(trigger());

    expect((await screen.findAllByRole("option")).map((option) => option.textContent)).toContain(
      "Выключенный",
    );
  });

  test.for([TaskStatus.IN_PROGRESS, TaskStatus.DONE])(
    "после запуска (%s) выбор недоступен",
    async (status, { api }) => {
      renderCard(api, { llm_account_id: "a1", status });

      await vi.waitFor(() => expect(trigger()).toHaveTextContent("Claude — основной"));
      expect(trigger()).toBeDisabled();
      expect(screen.getByText(/Сменить можно, вернув задачу в статус до запуска/)).toBeInTheDocument();
    },
  );
});
