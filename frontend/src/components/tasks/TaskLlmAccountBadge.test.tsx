import { screen } from "@testing-library/react";
import { describe, expect, vi } from "vitest";
import { TaskLlmAccountBadge } from "@/components/tasks/TaskLlmAccountBadge";
import type { Task } from "@/lib/types";
import type { MockedApi } from "@/test/apiMock";
import { makeLlmAccount, makeLlmProvider, makeTask } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const start = makeLlmAccount({ id: "a1", label: "Claude — основной", usage_5h_pct: "93.00" });
const spare = makeLlmAccount({
  id: "a2",
  label: "Codex — запасной",
  provider: "openai",
  default_model: "gpt-5.5-codex",
  usage_5h_pct: "4.00",
  usage_week_pct: "20.50",
});

function renderBadge(api: MockedApi, task: Partial<Task>) {
  api.respond("GET /llm-accounts", [start, spare]);
  api.respond("GET /llm-accounts/providers", [
    makeLlmProvider(),
    makeLlmProvider({ id: "openai", label: "Codex (OpenAI)" }),
  ]);
  return renderWithProviders(<TaskLlmAccountBadge task={makeTask(task)} />);
}

describe("TaskLlmAccountBadge", () => {
  test("текущий аккаунт — пометка, провайдер, модель и расход", async ({ api }) => {
    renderBadge(api, { llm_account_id: "a1", current_llm_account_id: "a2" });

    expect(await screen.findByLabelText("Текущий LLM-аккаунт")).toHaveTextContent(
      "Codex — запасной · Codex (OpenAI) · gpt-5.5-codex · 5 ч 4% · нед. 20.5%",
    );
  });

  test("до первого обращения — стартовый аккаунт", async ({ api }) => {
    renderBadge(api, { llm_account_id: "a1", current_llm_account_id: null });

    expect(await screen.findByLabelText("Текущий LLM-аккаунт")).toHaveTextContent("Claude — основной");
  });

  test("у задачи без LLM-аккаунта блока нет", async ({ api }) => {
    renderBadge(api, { llm_account_id: null });

    await vi.waitFor(() => expect(api.requests.map((request) => request.path)).toContain("/llm-accounts"));
    expect(screen.queryByLabelText("Текущий LLM-аккаунт")).not.toBeInTheDocument();
  });
});
