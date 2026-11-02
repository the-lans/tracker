import { screen } from "@testing-library/react";
import { describe, expect, vi } from "vitest";
import { LlmAccountForm } from "@/components/llmAccounts/LlmAccountForm";
import { ReasoningEffort, type LlmAccount } from "@/lib/types";
import type { MockedApi } from "@/test/apiMock";
import { makeLlmAccount, makeLlmProvider } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

function renderForm(api: MockedApi, account?: LlmAccount) {
  api.respond("GET /llm-accounts/providers", [
    makeLlmProvider(),
    makeLlmProvider({ id: "openai", label: "Codex (OpenAI)" }),
  ]);
  api.respond("GET /llm-accounts/acc1/models", ["claude-opus-5-5", "claude-sonnet-5-5"]);
  const onSaved = vi.fn();
  return { onSaved, ...renderWithProviders(<LlmAccountForm account={account} onSaved={onSaved} onCancel={() => {}} />) };
}

describe("LlmAccountForm", () => {
  test("новый аккаунт — пометка и провайдер", async ({ api }) => {
    const { user, onSaved } = renderForm(api);

    await user.type(screen.getByLabelText("Пометка"), "Codex — запасной");
    await user.click(screen.getByRole("combobox", { name: "Провайдер" }));
    await user.click(await screen.findByRole("option", { name: "Codex (OpenAI)" }));
    await user.click(screen.getByRole("button", { name: "Создать" }));

    expect(api.mutations()).toEqual([
      { method: "POST", path: "/llm-accounts", body: { label: "Codex — запасной", provider: "openai" } },
    ]);
    await vi.waitFor(() => expect(onSaved).toHaveBeenCalled());
  });

  test("без провайдера создать нельзя", async ({ api }) => {
    const { user } = renderForm(api);

    await user.type(screen.getByLabelText("Пометка"), "Аккаунт");

    expect(screen.getByRole("button", { name: "Создать" })).toBeDisabled();
  });

  test("правка отправляет только изменённые модель и уровень", async ({ api }) => {
    const { user } = renderForm(api, makeLlmAccount());

    await user.click(screen.getByRole("combobox", { name: "Модель по умолчанию" }));
    await user.click(await screen.findByRole("option", { name: "claude-sonnet-5-5" }));
    await user.click(screen.getByRole("combobox", { name: "Уровень рассуждений по умолчанию" }));
    await user.click(await screen.findByRole("option", { name: "максимальный" }));
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(api.mutations()).toEqual([
      {
        method: "PATCH",
        path: "/llm-accounts/acc1",
        body: {
          label: "Claude Max — команда",
          default_model: "claude-sonnet-5-5",
          default_effort: ReasoningEffort.MAX,
        },
      },
    ]);
  });

  test("до входа модели не запрашиваются", async ({ api }) => {
    renderForm(api, makeLlmAccount({ signed_in: false }));

    expect(await screen.findByText("Список моделей появится после входа в аккаунт.")).toBeInTheDocument();
    expect(api.requests.some((request) => request.path.endsWith("/models"))).toBe(false);
    expect(screen.queryByLabelText("Провайдер")).not.toBeInTheDocument();
  });
});
