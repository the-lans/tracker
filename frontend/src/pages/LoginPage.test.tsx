import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, vi } from "vitest";
import { AuthContext, type AuthContextValue } from "@/stores/authContext";
import { makeCurrentUser } from "@/test/factories";
import { test } from "@/test/fixtures";

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

function renderLogin(login: AuthContextValue["login"] = vi.fn()) {
  const auth: AuthContextValue = { token: null, user: null, isAuthenticated: false, login, logout: () => {} };
  render(
    <AuthContext.Provider value={auth}>
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>
    </AuthContext.Provider>,
  );
  return { login };
}

describe("LoginPage", () => {
  beforeEach(stubGoogleButton);

  test("отказ во входе остаётся на странице с причиной от сервера", async ({ api }) => {
    api.respond("POST /auth/google", { error: { status: 403, message: REFUSAL } });
    const { login } = renderLogin();

    await userEvent.click(await screen.findByRole("button", { name: "Войти через Google" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(REFUSAL);
    expect(login).not.toHaveBeenCalled();
  });

  test("успешный вход сохраняет сессию без сообщения об отказе", async ({ api }) => {
    const user = makeCurrentUser();
    api.respond("POST /auth/google", { session_token: "session", user });
    const { login } = renderLogin();

    await userEvent.click(await screen.findByRole("button", { name: "Войти через Google" }));

    await vi.waitFor(() => expect(login).toHaveBeenCalledWith({ token: "session", user }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
