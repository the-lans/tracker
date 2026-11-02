import { screen } from "@testing-library/react";
import { describe, expect, vi } from "vitest";
import { LlmAccountLoginDialog } from "@/components/llmAccounts/LlmAccountLoginDialog";
import { useLlmAccounts } from "@/hooks/useLlmAccounts";
import { LlmLoginState } from "@/lib/types";
import type { MockedApi } from "@/test/apiMock";
import { makeLlmAccount } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const LOGIN = "/llm-accounts/acc1/login";
const REDIRECT = "http://localhost:54545/callback?code=example&state=st1";
const LOGIN_WINDOW_MS = 5 * 60 * 1000;

function loginStart(expiresInMs = LOGIN_WINDOW_MS) {
  return () => ({
    url: "https://auth.example.com/oauth?state=st1",
    state: "st1",
    expires_at: new Date(Date.now() + expiresInMs).toISOString(),
  });
}

/** Список аккаунтов на странице под диалогом — его перечитывает успешный вход. */
function AccountsList() {
  useLlmAccounts();
  return null;
}

function renderDialog(api: MockedApi, expiresInMs?: number) {
  api.respond(`POST ${LOGIN}`, loginStart(expiresInMs));
  const onClose = vi.fn();
  return {
    onClose,
    ...renderWithProviders(
      <>
        <AccountsList />
        <LlmAccountLoginDialog account={makeLlmAccount()} onClose={onClose} />
      </>,
    ),
  };
}

function accountListReads(api: MockedApi) {
  return api.requests.filter((request) => request.method === "GET" && request.path === "/llm-accounts");
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
    // При открытии, после адреса (ответ `wait`) и после `ok` из опроса статуса.
    await vi.waitFor(() => expect(accountListReads(api)).toHaveLength(3));
  });

  test("показывает, сколько ждёт прокси", async ({ api }) => {
    renderDialog(api);

    expect(await screen.findByText(/^Осталось [45]:\d\d$/)).toBeInTheDocument();
  });

  test("истёкший вход предлагает начать заново", async ({ api }) => {
    const { user } = renderDialog(api, -1000);

    expect(await screen.findByRole("alert")).toHaveTextContent("Время входа истекло — начните вход заново.");
    expect(screen.queryByRole("link", { name: "Открыть страницу входа" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Завершить вход" })).not.toBeInTheDocument();

    api.respond(`POST ${LOGIN}`, loginStart());
    await user.click(screen.getByRole("button", { name: "Начать заново" }));

    expect(await screen.findByRole("link", { name: "Открыть страницу входа" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(api.mutations().filter((request) => request.path === LOGIN)).toHaveLength(2);
  });

  test("ошибка входа показывается", async ({ api }) => {
    api.respond(`POST ${LOGIN}/callback`, { state: LlmLoginState.ERROR, error: "state не совпадает" });
    const { user, onClose } = renderDialog(api);

    await submitRedirect(user);

    expect(await screen.findByRole("alert")).toHaveTextContent("state не совпадает");
    expect(screen.getByRole("button", { name: "Начать заново" })).toBeEnabled();
    expect(onClose).not.toHaveBeenCalled();
  });

  test("неверный адрес — ошибка под полем, вход продолжается", async ({ api, toasts }) => {
    api.respond(`POST ${LOGIN}/callback`, {
      error: { status: 422, message: "Это не адрес после входа" },
    });
    const { user } = renderDialog(api);

    await submitRedirect(user);

    const field = screen.getByLabelText("Адрес после входа");
    expect(await screen.findByRole("alert")).toHaveTextContent("Это не адрес после входа");
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(toasts.error).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Завершить вход" })).toBeInTheDocument();

    await user.type(field, "x");

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  test("отмена отменяет вход в прокси", async ({ api }) => {
    const { user, onClose } = renderDialog(api);

    await screen.findByRole("link", { name: "Открыть страницу входа" });
    await user.click(screen.getByRole("button", { name: "Отмена" }));

    expect(api.mutations().at(-1)).toEqual({ method: "DELETE", path: LOGIN, body: undefined });
    await vi.waitFor(() => expect(onClose).toHaveBeenCalled());
  });
});
