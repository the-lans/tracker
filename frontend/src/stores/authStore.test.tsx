import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { expect, test, vi } from "vitest";
import { ProtectedRoute } from "@/components/layout/ProtectedRoute";
import { AuthProvider } from "@/stores/authStore";
import { advanceSession, expireStoredSession, sessionGeneration } from "@/stores/authContext";
import { useAuth } from "@/hooks/useAuth";
import { useState } from "react";
import { makeCurrentUser } from "@/test/factories";
import { createTestQueryClient } from "@/test/renderWithProviders";

function renderApp() {
  const client = createTestQueryClient();
  client.setQueryData(["private"], "secret");
  render(<QueryClientProvider client={client}><AuthProvider>
    <MemoryRouter initialEntries={["/"]}><Routes>
      <Route path="/login" element={<p>Страница входа</p>} />
      <Route element={<ProtectedRoute />}><Route path="/" element={<p>Задачи</p>} /></Route>
    </Routes></MemoryRouter>
  </AuthProvider></QueryClientProvider>);
  return client;
}

test("cookie bootstrap, удаление старого токена, очистка приватного кэша", async () => {
  localStorage.setItem("tracker.session", "old-secret");
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(makeCurrentUser()))));
  const client = renderApp();
  expect(await screen.findByText("Задачи")).toBeInTheDocument();
  expect(localStorage.getItem("tracker.session")).toBeNull();
  client.setQueryData(["private"], "secret");
  act(() => expireStoredSession(sessionGeneration()));
  expect(await screen.findByText("Страница входа")).toBeInTheDocument();
  expect(client.getQueryData(["private"])).toBeUndefined();
});

test("поздний 401 не завершает новый вход", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(makeCurrentUser()))));
  renderApp();
  await screen.findByText("Задачи");
  const previous = sessionGeneration();
  act(() => { advanceSession(); expireStoredSession(previous); });
  expect(screen.getByText("Задачи")).toBeInTheDocument();
});

test("изменение сессии в другой вкладке перечитывает сервер", async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(makeCurrentUser())))
    .mockResolvedValueOnce(new Response("{}", { status: 401 }));
  vi.stubGlobal("fetch", fetcher);
  renderApp();
  await screen.findByText("Задачи");
  act(() => window.dispatchEvent(new StorageEvent("storage", { key: "tracker.auth-change" })));
  expect(await screen.findByText("Страница входа")).toBeInTheDocument();
});

function Controls() {
  const { user, login, logout } = useAuth();
  const [failure, setFailure] = useState(false);
  return <>
    <p>{user?.email ?? "Нет сессии"}</p>
    <button onClick={() => login(makeCurrentUser({ email: "new@example.com" }))}>Новый вход</button>
    <button onClick={() => { void logout().catch(() => setFailure(true)); }}>Выход</button>
    {failure && <p>Ошибка выхода</p>}
  </>;
}

function renderControls() {
  const client = createTestQueryClient();
  render(<QueryClientProvider client={client}><AuthProvider><Controls /></AuthProvider></QueryClientProvider>);
  return client;
}

test("ошибка серверного выхода сохраняет вход и приватный кэш", async () => {
  vi.stubGlobal("fetch", vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify(makeCurrentUser({ email: "current@example.com" }))))
    .mockRejectedValueOnce(new TypeError("network")));
  const client = renderControls();
  await screen.findByText("current@example.com");
  client.setQueryData(["private"], "secret");
  fireEvent.click(screen.getByText("Выход"));
  await screen.findByText("Ошибка выхода");
  expect(screen.getByText("current@example.com")).toBeInTheDocument();
  expect(client.getQueryData(["private"])).toBe("secret");
});

test("поздний 401 bootstrap не стирает пользователя нового входа", async () => {
  let resolve!: (response: Response) => void;
  vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(done => { resolve = done; })));
  renderControls();
  fireEvent.click(screen.getByText("Новый вход"));
  expect(screen.getByText("new@example.com")).toBeInTheDocument();
  await act(async () => resolve(new Response("{}", { status: 401 })));
  expect(screen.getByText("new@example.com")).toBeInTheDocument();
});

test("сбой bootstrap не открывает защищённую страницу", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("network"); }));
  renderApp();
  expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось проверить сессию");
  expect(screen.queryByText("Задачи")).not.toBeInTheDocument();
});
