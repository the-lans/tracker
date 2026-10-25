import { vi } from "vitest";

/** Запрос, ушедший в API: путь — без префикса `/api` и без query-строки. */
export interface RecordedRequest {
  method: string;
  path: string;
  body: unknown;
}

/** Ответ API: JSON-тело или ошибка с HTTP-статусом и сообщением сервера. */
export type MockResponse = unknown | { error: { status: number; message: string } };

/** Ключ маршрута — «МЕТОД /путь», например `"POST /tasks/t1/start"`. */
export type MockRoutes = Record<string, MockResponse | ((body: unknown) => MockResponse)>;

const API_PREFIX = "/api";

function isErrorResponse(value: unknown): value is { error: { status: number; message: string } } {
  return typeof value === "object" && value !== null && "error" in value;
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/**
 * Подменяет `fetch`: ответы берутся из `routes`, неописанный GET возвращает
 * пустой список, неописанный запрос на изменение — 204. Все запросы
 * записываются, чтобы тест проверял, что именно ушло на сервер.
 */
export type MockedApi = ReturnType<typeof mockApi>;

export function mockApi(initialRoutes: MockRoutes = {}) {
  const routes: MockRoutes = { ...initialRoutes };
  const requests: RecordedRequest[] = [];

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), window.location.origin);
    const method = init?.method ?? "GET";
    const path = url.pathname.replace(API_PREFIX, "");
    const body = typeof init?.body === "string" ? (JSON.parse(init.body) as unknown) : undefined;
    requests.push({ method, path, body });

    const route = routes[`${method} ${path}`];
    const response: unknown = await (typeof route === "function" ? route(body) : route);
    if (response === undefined) {
      return method === "GET" ? jsonResponse(200, []) : new Response(null, { status: 204 });
    }
    if (isErrorResponse(response)) {
      return jsonResponse(response.error.status, {
        error: { code: "error", message: response.error.message },
      });
    }
    return jsonResponse(200, response);
  });
  vi.stubGlobal("fetch", fetchMock);

  return {
    requests,
    /** Задаёт ответ маршрута «МЕТОД /путь» для этого теста. */
    respond: (route: string, response: MockRoutes[string]) => {
      routes[route] = response;
    },
    /** Запросы на изменение (без GET) — то, что сделал пользователь. */
    mutations: () => requests.filter((request) => request.method !== "GET"),
  };
}
