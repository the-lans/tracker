import { act, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, test } from "vitest";
import { ProtectedRoute } from "@/components/layout/ProtectedRoute";
import { AuthProvider } from "@/stores/authStore";
import { expireStoredSession, writeStoredSession } from "@/stores/authContext";
import { makeCurrentUser } from "@/test/factories";

const TOKEN = "session-token-123";

function renderApp() {
  render(
    <AuthProvider>
      <MemoryRouter initialEntries={["/llm-accounts"]}>
        <Routes>
          <Route path="/login" element={<p>Страница входа</p>} />
          <Route element={<ProtectedRoute />}>
            <Route path="/llm-accounts" element={<p>LLM-аккаунты</p>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </AuthProvider>,
  );
}

describe("AuthProvider", () => {
  afterEach(() => writeStoredSession(null));

  test.for([
    { name: "отвергнутый токен — страница входа", expiredToken: TOKEN, page: "Страница входа" },
    { name: "чужой токен — сессия цела", expiredToken: "old-token", page: "LLM-аккаунты" },
  ])("$name", ({ expiredToken, page }) => {
    writeStoredSession({ token: TOKEN, user: makeCurrentUser() });
    renderApp();
    expect(screen.getByText("LLM-аккаунты")).toBeInTheDocument();

    act(() => expireStoredSession(expiredToken));

    expect(screen.getByText(page)).toBeInTheDocument();
  });

  test.for([
    { name: "выход в другой вкладке — страница входа", key: "tracker.session", page: "Страница входа" },
    { name: "очистка хранилища — страница входа", key: null, page: "Страница входа" },
    { name: "чужой ключ — сессия цела", key: "tracker.theme", page: "LLM-аккаунты" },
  ])("$name", ({ key, page }) => {
    writeStoredSession({ token: TOKEN, user: makeCurrentUser() });
    renderApp();

    // Другая вкладка удалила сессию: в этой вкладке приходит только событие.
    writeStoredSession(null);
    act(() => window.dispatchEvent(new StorageEvent("storage", { key })));

    expect(screen.getByText(page)).toBeInTheDocument();
  });
});
