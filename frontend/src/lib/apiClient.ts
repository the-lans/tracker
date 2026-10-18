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

async function request<TResponse>(path: string, options: RequestOptions = {}): Promise<TResponse> {
  const token = getStoredToken();
  const headers: Record<string, string> = {};
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  let body: BodyInit | undefined;
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }

  const response = await fetch(buildUrl(path, options.params), {
    method: options.method ?? "GET",
    headers,
    body,
  });

  if (response.status === 204) {
    return undefined as TResponse;
  }

  const text = await response.text();
  const data = text ? (JSON.parse(text) as unknown) : undefined;

  if (!response.ok) {
    throw new ApiError(response.status, (data as ApiErrorBody | undefined) ?? null);
  }

  return data as TResponse;
}

export const api = {
  get: <T>(path: string, params?: Record<string, QueryParamValue>) =>
    request<T>(path, { method: "GET", params }),
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: "POST", body }),
  patch: <T>(path: string, body?: unknown) => request<T>(path, { method: "PATCH", body }),
  delete: <T = void>(path: string) => request<T>(path, { method: "DELETE" }),
};

export function wsUrl(path: string): string {
  const token = getStoredToken();
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const url = new URL(`${protocol}//${window.location.host}${path}`);
  if (token) {
    url.searchParams.set("token", token);
  }
  return url.toString();
}
