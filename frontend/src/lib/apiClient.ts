import { getStoredToken } from "@/stores/authStore";
import type { ApiErrorBody } from "@/lib/types";

/**
 * Базовый путь REST API. В деве проксируется Vite'ом (см. `vite.config.ts`,
 * `server.proxy["/api"]`, срезающий этот префикс перед обращением к
 * backend — сами FastAPI-роуты в `backend/main.py` смонтированы БЕЗ
 * `/api`, напрямую как `/tasks`, `/auth/google` и т.д.). В проде значение
 * переопределяется `VITE_API_BASE_URL`; `deploy/caddy/Caddyfile` срезает
 * тот же префикс через `handle_path /api/*`.
 */
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "/api";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | undefined;

  constructor(status: number, body: ApiErrorBody | null) {
    super(body?.error.message ?? `Ошибка запроса (HTTP ${status})`);
    this.status = status;
    this.code = body?.error.code ?? "unknown_error";
    this.requestId = body?.error.request_id;
  }
}

type QueryParamValue = string | number | boolean | null | undefined;

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE" | "PUT";
  body?: unknown;
  params?: Record<string, QueryParamValue>;
}

function buildUrl(path: string, params?: Record<string, QueryParamValue>): string {
  const url = new URL(`${API_BASE_URL}${path}`, window.location.origin);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && value !== "") {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return `${url.pathname}${url.search}`;
}

function authHeaders(): Record<string, string> {
  const token = getStoredToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function errorOf(response: Response): Promise<ApiError> {
  const text = await response.text();
  let body: ApiErrorBody | null = null;
  try {
    body = text ? (JSON.parse(text) as ApiErrorBody) : null;
  } catch {
    // Ответ не JSON (например, прокси) — сообщение будет общим.
  }
  return new ApiError(response.status, body);
}

async function request<TResponse>(path: string, options: RequestOptions = {}): Promise<TResponse> {
  const headers = authHeaders();
  let body: BodyInit | undefined;
  if (options.body instanceof Blob) {
    // Раздел 14.3: файл артефакта уходит телом запроса как есть.
    headers["Content-Type"] = options.body.type || "application/octet-stream";
    body = options.body;
  } else if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }

  const response = await fetch(buildUrl(path, options.params), {
    method: options.method ?? "GET",
    headers,
    body,
  });

  if (!response.ok) {
    throw await errorOf(response);
  }
  if (response.status === 204) {
    return undefined as TResponse;
  }

  const text = await response.text();
  return (text ? (JSON.parse(text) as unknown) : undefined) as TResponse;
}

/** Файл целиком (скачивание артефакта): авторизация — тем же токеном, что у API. */
async function getBlob(path: string): Promise<Blob> {
  const response = await fetch(buildUrl(path), { headers: authHeaders() });
  if (!response.ok) {
    throw await errorOf(response);
  }
  return response.blob();
}

export const api = {
  get: <T>(path: string, params?: Record<string, QueryParamValue>) =>
    request<T>(path, { method: "GET", params }),
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: "POST", body }),
  patch: <T>(path: string, body?: unknown) => request<T>(path, { method: "PATCH", body }),
  put: <T>(path: string, body?: unknown) => request<T>(path, { method: "PUT", body }),
  delete: <T = void>(path: string) => request<T>(path, { method: "DELETE" }),
  getBlob,
};

/** Адрес WebSocket без токена: адрес попадает в журналы запросов (раздел 18.1). */
export function wsUrl(path: string): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}${path}`;
}

/** Первое сообщение сокета задачи — токен сессии (раздел 18.1). */
export function wsAuthMessage(): string {
  return JSON.stringify({ type: "auth", token: getStoredToken() ?? "" });
}
