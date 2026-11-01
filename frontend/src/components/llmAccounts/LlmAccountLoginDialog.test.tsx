import { screen } from "@testing-library/react";
import { describe, expect, vi } from "vitest";
import { LlmAccountLoginDialog } from "@/components/llmAccounts/LlmAccountLoginDialog";
import { LlmLoginState } from "@/lib/types";
import type { MockedApi } from "@/test/apiMock";
import { makeLlmAccount } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const LOGIN = "/llm-accounts/acc1/login";
const REDIRECT = "http://localhost:54545/callback?code=example&state=st1";

function renderDialog(api: MockedApi) {
  api.respond(`POST ${LOGIN}`, { url: "https://auth.example.com/oauth?state=st1", state: "st1" });
  const onClose = vi.fn();
  return { onClose, ...renderWithProviders(<LlmAccountLoginDialog account={makeLlmAccount()} onClose={onClose} />) };
}

async function submitRedirect(user: ReturnType<typeof renderDialog>["user"]) {
  await screen.findByRole("link", { name: "Открыть страницу входа" });
  await user.type(screen.getByLabelText("Адрес после входа"), REDIRECT);
  await user.click(screen.getByRole("button", { name: "Завершить вход" }));
}

describe("LlmAccountLoginDialog", () => {
  test("открывает ссылку входа прокси", async ({ api }) => {
    renderDialog(api);

    expect(await screen.findByRole("link", { name: "Открыть страницу входа" })).toHaveAttribute(
      "href",
      "https://auth.example.com/oauth?state=st1",
    );
  });

  test("адрес после входа завершает вход", async ({ api, toasts }) => {
    api.respond(`POST ${LOGIN}/callback`, { state: LlmLoginState.OK, error: null });
    const { user, onClose } = renderDialog(api);

    await submitRedirect(user);

    expect(api.mutations()).toEqual([
      { method: "POST", path: LOGIN, body: undefined },
      { method: "POST", path: `${LOGIN}/callback`, body: { redirect_url: REDIRECT } },
    ]);
    await vi.waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(toasts.success).toHaveBeenCalledWith("Вход в «Claude Max — команда» выполнен");
  });

  test("пока прокси обменивает код — опрос статуса до итога", async ({ api }) => {
    api.respond(`POST ${LOGIN}/callback`, { state: LlmLoginState.WAIT, error: null });
    api.respond(`GET ${LOGIN}/status`, { state: LlmLoginState.OK, error: null });
    const { user, onClose } = renderDialog(api);

    await submitRedirect(user);

    await vi.waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(api.requests.filter((request) => request.path === `${LOGIN}/status`)).not.toHaveLength(0);
  });

  test("ошибка входа показывается", async ({ api }) => {
    api.respond(`POST ${LOGIN}/callback`, { state: LlmLoginState.ERROR, error: "state не совпадает" });
    const { user, onClose } = renderDialog(api);

    await submitRedirect(user);

    expect(await screen.findByRole("alert")).toHaveTextContent("state не совпадает");
    expect(onClose).not.toHaveBeenCalled();
  });

  test("отмена отменяет вход в прокси", async ({ api }) => {
    const { user, onClose } = renderDialog(api);

    await screen.findByRole("link", { name: "Открыть страницу входа" });
    await user.click(screen.getByRole("button", { name: "Отмена" }));

    expect(api.mutations().at(-1)).toEqual({ method: "DELETE", path: LOGIN, body: undefined });
    await vi.waitFor(() => expect(onClose).toHaveBeenCalled());
  });
});
