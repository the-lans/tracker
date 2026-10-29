import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, wsAuthMessage, wsUrl } from "@/lib/apiClient";
import { errorMessage } from "@/lib/errors";
import { writeStoredSession } from "@/stores/authContext";
import { makeCurrentUser } from "@/test/factories";

const TOKEN = "session-token-123";

function stubFetch(response: Response) {
  const fetchMock = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(
    async () => response,
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("apiClient", () => {
  beforeEach(() => writeStoredSession({ token: TOKEN, user: makeCurrentUser() }));
  afterEach(() => writeStoredSession(null));

  describe("запрос", () => {
    it("токен сессии — в заголовке, тело — JSON", async () => {
      const fetchMock = stubFetch(json(200, { id: "t1" }));

      await expect(api.post("/tasks", { code: "RR-12345" })).resolves.toEqual({ id: "t1" });

      const [url, init] = fetchMock.mock.calls[0];
      expect(url).toBe("/api/tasks");
      expect(init).toMatchObject({
        method: "POST",
        headers: { Authorization: `Bearer ${TOKEN}`, "Content-Type": "application/json" },
        body: JSON.stringify({ code: "RR-12345" }),
      });
    });

    it("без входа — без заголовка авторизации", async () => {
      writeStoredSession(null);
      const fetchMock = stubFetch(json(200, []));

      await api.get("/tasks");

      expect(fetchMock.mock.calls[0][1]?.headers).toEqual({});
    });

    it("пустые параметры не попадают в адрес", async () => {
      const fetchMock = stubFetch(json(200, []));

      await api.get("/tasks", { status_filter: "done", search: "", page: null, limit: 0 });

      expect(fetchMock.mock.calls[0][0]).toBe("/api/tasks?status_filter=done&limit=0");
    });

    it("файл уходит как есть, со своим типом", async () => {
      const fetchMock = stubFetch(json(200, {}));
      const file = new Blob(["a;b"], { type: "text/csv" });

      await api.put("/tasks/t1/artifacts/report.csv", file);

      expect(fetchMock.mock.calls[0][1]).toMatchObject({ body: file, headers: { "Content-Type": "text/csv" } });
    });

    it.each([
      ["204", () => new Response(null, { status: 204 })],
      ["пустое тело", () => new Response("", { status: 200 })],
    ])("%s → undefined", async (_case, response) => {
      stubFetch(response());

      await expect(api.delete("/tasks/t1")).resolves.toBeUndefined();
    });
  });

  describe("ошибка", () => {
    it("статус, код и сообщение сервера", async () => {
      stubFetch(json(409, { error: { code: "conflict", message: "Задача уже запущена", request_id: "req-1" } }));

      const error = await api.post("/tasks/t1/start").catch((caught: unknown) => caught);

      expect(error).toBeInstanceOf(ApiError);
      expect(error).toMatchObject({ status: 409, code: "conflict", message: "Задача уже запущена", requestId: "req-1" });
      expect(errorMessage(error, "Не удалось запустить")).toBe("Задача уже запущена");
    });

    it.each([
      ["не JSON (прокси)", new Response("<html>Bad Gateway</html>", { status: 502 })],
      ["JSON не в формате API", json(502, { detail: [{ msg: "Field required" }] })],
      ["пустое тело", new Response(null, { status: 502 })],
    ])("ответ %s — общее сообщение со статусом", async (_case, response) => {
      stubFetch(response);

      const error = await api.get("/tasks").catch((caught: unknown) => caught);

      expect(error).toBeInstanceOf(ApiError);
      expect(error).toMatchObject({ status: 502, code: "unknown_error", message: "Ошибка запроса (HTTP 502)" });
    });

    it.each([
      ["сетевая ошибка", new TypeError("Failed to fetch")],
      ["не ошибка", "строка"],
    ])("%s — запасной текст", (_case, error) => {
      expect(errorMessage(error, "Не удалось сохранить")).toBe("Не удалось сохранить");
    });
  });

  describe("WebSocket (раздел 18.1)", () => {
    it("токен не попадает в адрес, а уходит первым сообщением", () => {
      const url = wsUrl("/ws/tasks/t1/status");

      expect(url).toBe(`ws://${window.location.host}/ws/tasks/t1/status`);
      expect(url).not.toContain(TOKEN);
      expect(JSON.parse(wsAuthMessage())).toEqual({ type: "auth", token: TOKEN });
    });
  });
});
