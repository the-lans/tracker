import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, vi } from "vitest";
import { makeCurrentUser } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

vi.hoisted(() => vi.stubEnv("VITE_GOOGLE_CLIENT_ID", "test-client.apps.googleusercontent.com"));
const { LoginPage } = await import("@/pages/LoginPage");

const REFUSAL = "Вход для outsider@example.com не разрешён — попросите администратора добавить этот email в список допуска";

/** Кнопка Google заменена своей: нажатие отдаёт `credential`, как это делает Google. */
function stubGoogleButton() {
  let callback: (response: { credential: string }) => void = () => {};
  window.google = {
    accounts: {
      id: {
        initialize: (config) => {
          callback = config.callback;
        },
        renderButton: (parent) => {
          const button = document.createElement("button");
          button.textContent = "Войти через Google";
          button.onclick = () => callback({ credential: "fake.jwt.token" });
          parent.append(button);
        },
        prompt: () => {},
      },
    },
  };
}

function renderLogin() {
  const login = vi.fn();
  return { login, ...renderWithProviders(<LoginPage />, { currentUser: null, login }) };
}

describe("LoginPage", () => {
  beforeEach(stubGoogleButton);

  test("отказ во входе остаётся на странице с причиной от сервера", async ({ api }) => {
    api.respond("POST /auth/google", { error: { status: 403, message: REFUSAL } });
    const { login, user } = renderLogin();

    await user.click(await screen.findByRole("button", { name: "Войти через Google" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(REFUSAL);
    expect(login).not.toHaveBeenCalled();
  });

  test("успешный вход сохраняет сессию без сообщения об отказе", async ({ api }) => {
    const currentUser = makeCurrentUser();
    api.respond("POST /auth/google", { session_token: "session", user: currentUser });
    const { login, user } = renderLogin();

    await user.click(await screen.findByRole("button", { name: "Войти через Google" }));

    await vi.waitFor(() => expect(login).toHaveBeenCalledWith({ token: "session", user: currentUser }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
