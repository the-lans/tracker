import type { ReactElement, ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, renderHook } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import type { CurrentUser } from "@/lib/types";
import { AuthContext, type AuthContextValue } from "@/stores/authContext";
import { makeCurrentUser } from "@/test/factories";

/**
 * Рендер с тем окружением, что у страниц: кеш запросов (без повторов),
 * роутер и вошедший пользователь (по умолчанию — обычный, не admin).
 */
export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

/** Хук с кешем запросов `queryClient` — его состояние тест проверяет напрямую. */
export function renderHookWithClient<TResult, TProps>(
  hook: (props: TProps) => TResult,
  { queryClient = createTestQueryClient(), initialProps }: { queryClient?: QueryClient; initialProps?: TProps } = {},
) {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { ...renderHook(hook, { wrapper, initialProps }), queryClient };
}

/** ``currentUser: null`` — пользователь не вошёл (страница входа); ``login`` — вход, который проверяет тест. */
export function renderWithProviders(
  ui: ReactElement,
  {
    currentUser = makeCurrentUser(),
    login = () => {},
  }: { currentUser?: CurrentUser | null; login?: AuthContextValue["login"] } = {},
) {
  const queryClient = createTestQueryClient();
  const auth: AuthContextValue = {
    token: currentUser ? "test-token" : null,
    user: currentUser,
    isAuthenticated: currentUser !== null,
    login,
    logout: () => {},
  };
  const wrap = (element: ReactElement) => (
    <QueryClientProvider client={queryClient}>
      <AuthContext.Provider value={auth}>
        <MemoryRouter>{element}</MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>
  );
  const user = userEvent.setup();
  const result = render(wrap(ui));
  // Новые пропсы — в том же окружении, без перемонтирования компонента.
  const rerender = (next: ReactElement) => result.rerender(wrap(next));
  return { ...result, rerender, user };
}
