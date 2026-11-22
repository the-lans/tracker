import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, vi } from "vitest";
import { Composer } from "@/components/tasks/Composer";
import { ManualRequestStatus, ManualRequestType, TaskStatus } from "@/lib/types";
import type { MockedApi } from "@/test/apiMock";
import { makeManualRequest } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const FREEFORM_PATH = "/tasks/t1/freeform";
const PREVIEW_PATH = "/templates/preview";
const OPEN_COMPOSER = "Свободный промт — задать вопрос сессии в любой момент";

function renderComposer({
  status = TaskStatus.IN_PROGRESS,
  llmAvailable = true,
  manualRequestsClosed = false,
}: { status?: TaskStatus; llmAvailable?: boolean; manualRequestsClosed?: boolean } = {}) {
  return renderWithProviders(
    <Composer taskId="t1" taskStatus={status} llmAvailable={llmAvailable} manualRequestsClosed={manualRequestsClosed} />,
  );
}

async function openComposer() {
  const view = renderComposer();
  await view.user.click(screen.getByRole("button", { name: OPEN_COMPOSER }));
  return { ...view, field: screen.getByRole("textbox") };
}

describe("Composer", () => {
  describe("доступность", () => {
    test("финализация закрывает новый ввод", () => {
      renderComposer({manualRequestsClosed: true});
      expect(screen.getByText("Задача завершается — приём новых промтов и команд закрыт")).toBeInTheDocument();
      expect(screen.queryByRole("button", {name: OPEN_COMPOSER})).not.toBeInTheDocument();
    });

    test("завершённая задача не отображается как завершающаяся", () => {
      renderComposer({status: TaskStatus.DONE, manualRequestsClosed: true});
      expect(screen.queryByText("Задача завершается — приём новых промтов и команд закрыт")).not.toBeInTheDocument();
      expect(screen.getByText("Свободный промт доступен, пока сессия задачи активна")).toBeInTheDocument();
    });

    test.for([
      TaskStatus.IN_PROGRESS,
      TaskStatus.PAUSED,
      TaskStatus.PLAN_REVIEW,
      TaskStatus.AWAITING_INPUT,
      TaskStatus.REBASE_CONFLICT,
      TaskStatus.AWAITING_LIMIT,
    ])("%s: промт можно написать", (status) => {
      renderComposer({ status });

      expect(screen.getByRole("button", { name: OPEN_COMPOSER })).toBeInTheDocument();
    });

    test.for([TaskStatus.QUEUED, TaskStatus.FAILED, TaskStatus.DONE])(
      "%s: сессия не активна — поле закрыто с пояснением",
      (status) => {
        renderComposer({ status });

        expect(screen.getByText("Свободный промт доступен, пока сессия задачи активна")).toBeInTheDocument();
        expect(screen.queryByRole("button", { name: OPEN_COMPOSER })).not.toBeInTheDocument();
      },
    );

    test("без доступного LLM-аккаунта в активной задаче доступны команды-скрипты", async () => {
      const { user } = renderComposer({ llmAvailable: false });
      await user.click(screen.getByRole("button", { name: OPEN_COMPOSER }));
      expect(screen.getByText("Нет доступного LLM-аккаунта — доступны только команды-скрипты.")).toBeInTheDocument();
      await user.type(screen.getByRole("textbox"), "Обычный текст");
      expect(screen.getByRole("button", { name: "Отправить" })).toBeDisabled();
    });

    test("без доступного LLM-аккаунта упавшая задача не принимает запросы", () => {
      renderComposer({ status: TaskStatus.FAILED, llmAvailable: false });
      expect(screen.getByText("Нет доступного LLM-аккаунта — свободный промт выполнить некому")).toBeInTheDocument();
      expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    });

    test.for([TaskStatus.NEW, TaskStatus.DEFINED, TaskStatus.READY, TaskStatus.NIGHT_WORKER])(
      "%s: чат — только в «Уточняется»",
      (status) => {
        renderComposer({ status });

        expect(screen.getByText("Переведите задачу в «Уточняется», чтобы обсудить её с агентом")).toBeInTheDocument();
        expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
      },
    );

    test("refining: сообщение агенту уходит свободным промтом", async ({ api }) => {
      const { user } = renderComposer({ status: TaskStatus.REFINING });

      await user.click(screen.getByRole("button", { name: "Сообщение агенту — обсудить задачу до запуска" }));
      await user.type(screen.getByRole("textbox"), "Что уточнить?");
      await user.click(screen.getByRole("button", { name: "Отправить" }));

      expect(api.mutations()).toEqual([
        { method: "POST", path: FREEFORM_PATH, body: { raw_prompt_text: "Что уточнить?" } },
      ]);
    });

    test("refining без доступного LLM-аккаунта: чат вести некому", () => {
      renderComposer({ status: TaskStatus.REFINING, llmAvailable: false });

      expect(screen.getByText("Нет доступного LLM-аккаунта — войдите в аккаунт на странице «LLM-аккаунты», чтобы обсудить задачу с агентом")).toBeInTheDocument();
      expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    });

  });

  describe("отправка", () => {
    test("поле расширяется за верхнюю ручку и стрелками клавиатуры", async ({ onTestFinished }) => {
      class TestPointerEvent extends MouseEvent {
        pointerId: number;
        constructor(type: string, init: PointerEventInit) {
          super(type, init);
          this.pointerId = init.pointerId ?? 0;
        }
      }
      vi.stubGlobal("PointerEvent", TestPointerEvent);
      onTestFinished(() => { vi.unstubAllGlobals(); });
      const { user, field } = await openComposer();
      vi.spyOn(field, "getBoundingClientRect").mockReturnValue({ height: 64 } as DOMRect);
      const handle = screen.getByRole("button", { name: "Изменить высоту поля ввода" });
      handle.setPointerCapture = vi.fn();
      fireEvent.pointerDown(handle, { pointerId: 1, button: 0, clientY: 300 });
      fireEvent.pointerMove(handle, { pointerId: 1, clientY: 220 });
      fireEvent.pointerUp(handle, { pointerId: 1 });
      expect(field).toHaveStyle({ height: "144px" });
      handle.focus();
      await user.keyboard("{ArrowUp}");
      expect(field).toHaveStyle({ height: "88px" });
    });

    test("на телефоне Enter вставляет строку, а кнопка отправляет сообщение", async ({ api, onTestFinished }) => {
      const userAgent = vi.spyOn(navigator, "userAgent", "get").mockReturnValue("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)");
      onTestFinished(() => userAgent.mockRestore());
      const { user, field } = await openComposer();
      await user.type(field, "Первая{Enter}Вторая");
      expect(field).toHaveValue("Первая\nВторая");
      expect(field).toHaveAttribute("enterkeyhint", "enter");
      expect(api.mutations()).toEqual([]);
      expect(screen.getByRole("button", { name: "Отправить" })).toHaveAttribute("title", "Отправить сообщение; Enter — новая строка");
      await user.click(screen.getByRole("button", { name: "Отправить" }));
      expect(api.mutations()).toEqual([
        { method: "POST", path: FREEFORM_PATH, body: { raw_prompt_text: "Первая\nВторая" } },
      ]);
    });

    test("Enter отправляет сообщение, Ctrl + Enter вставляет строку в позиции курсора", async ({ api }) => {
      const { user, field } = await openComposer();
      await user.type(field, "ПерваяВторая");
      (field as HTMLTextAreaElement).setSelectionRange(6, 6);
      await user.keyboard("{Control>}{Enter}{/Control}");
      expect(field).toHaveValue("Первая\nВторая");
      expect(api.mutations()).toEqual([]);
      expect(screen.getByRole("button", { name: "Отправить" })).toHaveAttribute(
        "title", "Enter — отправить; Ctrl + Enter — новая строка",
      );
      await user.keyboard("{Enter}");
      expect(api.mutations()).toEqual([
        { method: "POST", path: FREEFORM_PATH, body: { raw_prompt_text: "Первая\nВторая" } },
      ]);
    });

    test.for(["", "   "])("текст «%s» отправить нельзя", async (text) => {
      const { user, field } = await openComposer();

      if (text) await user.type(field, text);

      expect(screen.getByRole("button", { name: "Отправить" })).toBeDisabled();
      expect(screen.getByRole("button", { name: "Предпросмотр подстановки" })).toBeDisabled();
    });

    test("промт уходит без пробелов по краям, поле закрывается", async ({ api, toasts }) => {
      const { user, field } = await openComposer();

      await user.type(field, "  Проверь выгрузку  ");
      await user.click(screen.getByRole("button", { name: "Отправить" }));

      expect(api.mutations()).toEqual([
        { method: "POST", path: FREEFORM_PATH, body: { raw_prompt_text: "Проверь выгрузку" } },
      ]);
      await expect.poll(() => toasts.success.mock.calls).toEqual([["Промт поставлен в очередь"]]);
      expect(screen.getByRole("button", { name: OPEN_COMPOSER })).toBeInTheDocument();
    });

    test("ошибка отправки сохраняет текст", async ({ api, toasts }) => {
      api.respond(`POST ${FREEFORM_PATH}`, { error: { status: 409, message: "Сессия задачи завершена" } });
      const { user, field } = await openComposer();

      await user.type(field, "Проверь выгрузку");
      await user.click(screen.getByRole("button", { name: "Отправить" }));

      await expect.poll(() => toasts.error.mock.calls).toEqual([["Сессия задачи завершена"]]);
      expect(screen.getByRole("textbox")).toHaveValue("Проверь выгрузку");
    });
  });

  describe("предпросмотр", () => {
    async function previewWith(api: MockedApi, rendered: string) {
      api.respond(`POST ${PREVIEW_PATH}`, { rendered_text: rendered });
      const view = await openComposer();
      // Фигурные скобки — служебные символы user-event: экранируются удвоением.
      await view.user.type(view.field, "Ключ {{{{env.API_TOKEN}} для {{{{task.code}}");
      await view.user.click(screen.getByRole("button", { name: "Предпросмотр подстановки" }));
      return view;
    }

    test("показывает текст после подстановки, как его вернул сервер", async ({ api }) => {
      await previewWith(api, "Ключ •••••• для RR-12345");

      expect(await screen.findByText("Ключ •••••• для RR-12345")).toBeInTheDocument();
      expect(api.mutations()).toEqual([
        {
          method: "POST",
          path: PREVIEW_PATH,
          body: { text: "Ключ {{env.API_TOKEN}} для {{task.code}}", scope: "freeform", task_id: "t1" },
        },
      ]);
    });

    test("кнопка скрывает и повторно открывает предпросмотр", async ({ api }) => {
      const { user } = await previewWith(api, "Результат подстановки");
      await screen.findByText("Результат подстановки");
      const button = screen.getByRole("button", { name: "Предпросмотр подстановки" });
      expect(button).toHaveAttribute("aria-pressed", "true");
      expect(button).toHaveAttribute("title", "Скрыть предпросмотр");
      await user.click(button);
      expect(screen.queryByText("Результат подстановки")).not.toBeInTheDocument();
      expect(button).toHaveAttribute("aria-pressed", "false");
      await user.click(button);
      expect(await screen.findByText("Результат подстановки")).toBeInTheDocument();
      expect(api.mutations()).toHaveLength(2);
    });

    test("ответ на старый запрос не показывает предпросмотр после правки", async ({ api }) => {
      let resolvePreview!: (value: { rendered_text: string }) => void;
      api.respond(`POST ${PREVIEW_PATH}`, () => new Promise((resolve) => { resolvePreview = resolve; }));
      const { user, field } = await openComposer();
      await user.type(field, "Первый текст");
      await user.click(screen.getByRole("button", { name: "Предпросмотр подстановки" }));
      await user.type(field, " изменён");
      resolvePreview({ rendered_text: "Устаревший результат" });
      await expect.poll(() => screen.getByRole("button", { name: "Предпросмотр подстановки" })).not.toBeDisabled();
      expect(screen.queryByText("Устаревший результат")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Предпросмотр подстановки" })).toHaveAttribute("aria-pressed", "false");
    });

    test("правка текста убирает устаревший предпросмотр", async ({ api }) => {
      const { user, field } = await previewWith(api, "Ключ •••••• для RR-12345");
      await screen.findByText("После подстановки");

      await user.type(field, "!");

      expect(screen.queryByText("После подстановки")).not.toBeInTheDocument();
    });

    test("ошибка предпросмотра показывается уведомлением", async ({ api, toasts }) => {
      api.respond(`POST ${PREVIEW_PATH}`, { error: { status: 422, message: "Неизвестная переменная {{env.NOPE}}" } });
      const { user, field } = await openComposer();

      await user.type(field, "{{{{env.NOPE}}");
      await user.click(screen.getByRole("button", { name: "Предпросмотр подстановки" }));

      await expect.poll(() => toasts.error.mock.calls).toEqual([["Неизвестная переменная {{env.NOPE}}"]]);
      expect(screen.queryByText("После подстановки")).not.toBeInTheDocument();
    });
  });

  describe("очередь", () => {
    test("считает только свободные промты, ждущие в очереди", async ({ api }) => {
      api.respond("GET /tasks/t1/manual-queue", [
        makeManualRequest({ id: "mq1" }),
        makeManualRequest({ id: "mq2" }),
        makeManualRequest({ id: "mq3", status: ManualRequestStatus.PROCESSING }),
        makeManualRequest({ id: "mq4", request_type: ManualRequestType.LIBRARY_PROMPT }),
      ]);
      renderComposer();

      expect(await screen.findByText("В очереди: 2")).toBeInTheDocument();
    });

    describe("влитие в текущий ход", () => {
      const INJECT_PATH = "POST /tasks/t1/manual-queue/inject";
      const CANCEL_PATH = "POST /tasks/t1/manual-queue/inject/cancel";

      test("«Влить» отправляет запрос и сообщает об успехе", async ({ api, toasts }) => {
        api.respond("GET /tasks/t1/manual-queue", [makeManualRequest({ id: "mq1" })]);
        api.respond(INJECT_PATH, { ok: true, request_id: "mq1", reason: null, message: null });
        const { user } = renderComposer();

        await user.click(await screen.findByRole("button", { name: "Влить в текущий ход" }));

        await expect.poll(() => toasts.success.mock.calls).toEqual([["Промт влит в текущий ход"]]);
        expect(api.requests.some((r) => r.method === "POST" && r.path === "/tasks/t1/manual-queue/inject")).toBe(true);
      });

      test("отказ воркера показывается понятным текстом", async ({ api, toasts }) => {
        api.respond("GET /tasks/t1/manual-queue", [makeManualRequest({ id: "mq1" })]);
        api.respond(INJECT_PATH, { ok: false, request_id: null, reason: "awaiting_decision", message: null });
        const { user } = renderComposer();

        await user.click(await screen.findByRole("button", { name: "Влить в текущий ход" }));

        await expect.poll(() => toasts.error.mock.calls).toEqual([["Агент ждёт вашего решения — влить нельзя"]]);
      });

      test("в очереди только команды — «Влить» неактивна с подсказкой", async ({ api }) => {
        api.respond("GET /tasks/t1/manual-queue", [
          makeManualRequest({ id: "mq1", raw_prompt_text: "/compact" }),
          makeManualRequest({ id: "mq2", command_name: "review", raw_prompt_text: null }),
        ]);
        renderComposer();

        const button = await screen.findByRole("button", { name: "Влить в текущий ход" });

        expect(button).toBeDisabled();
        expect(button).toHaveAttribute("title", "В очереди только команды — их нельзя влить");
      });

      test("не в ходе агента «Влить» неактивна", async ({ api }) => {
        api.respond("GET /tasks/t1/manual-queue", [makeManualRequest({ id: "mq1" })]);
        renderComposer({ status: TaskStatus.PAUSED });

        expect(await screen.findByRole("button", { name: "Влить в текущий ход" })).toBeDisabled();
      });

      test("влитый промт: строка «Влито» и кнопка «Отменить»", async ({ api, toasts }) => {
        api.respond("GET /tasks/t1/manual-queue", [
          makeManualRequest({ id: "mq1", status: ManualRequestStatus.INJECTED }),
          makeManualRequest({ id: "mq2" }),
        ]);
        api.respond(CANCEL_PATH, { ok: true, request_id: "mq1", reason: null, message: null });
        const { user } = renderComposer();

        expect(await screen.findByText("В очереди: 1")).toBeInTheDocument();
        expect(screen.getByText("Влито: 1 — дойдёт после текущего шага")).toBeInTheDocument();
        await user.click(screen.getByRole("button", { name: "Отменить" }));

        await expect.poll(() => toasts.success.mock.calls).toEqual([["Промт возвращён в очередь"]]);
      });

      test("слишком поздно отменять — понятная причина", async ({ api, toasts }) => {
        api.respond("GET /tasks/t1/manual-queue", [makeManualRequest({ id: "mq1", status: ManualRequestStatus.INJECTED })]);
        api.respond(CANCEL_PATH, { ok: false, request_id: "mq1", reason: "too_late", message: null });
        const { user } = renderComposer();

        await user.click(await screen.findByRole("button", { name: "Отменить" }));

        await expect.poll(() => toasts.error.mock.calls).toEqual([["Агент уже взял промт — отменить нельзя"]]);
      });

      test("без влитых промтов кнопки «Отменить» нет", async ({ api }) => {
        api.respond("GET /tasks/t1/manual-queue", [makeManualRequest({ id: "mq1" })]);
        renderComposer();

        await screen.findByText("В очереди: 1");

        expect(screen.queryByRole("button", { name: "Отменить" })).not.toBeInTheDocument();
        expect(screen.queryByText(/Влито/)).not.toBeInTheDocument();
      });
    });

    test("пустая очередь — без индикатора", async ({ api }) => {
      renderComposer();
      await expect.poll(() => api.requests.length).toBeGreaterThan(0);

      expect(screen.queryByText(/В очереди/)).not.toBeInTheDocument();
    });
  });
});


describe("Команды библиотеки в чате", () => {
  test("поиск и выбор команды клавиатурой, передача аргументов", async ({ api }) => {
    api.respond("GET /tasks/t1/commands", [{
      id: "n1", name: "Ревью", slash_name: "review", argument_hint: "[сервис]",
      description: "Проверить изменения", node_type: "plain_prompt", revision: 3,
    }]);
    const { user, field } = await openComposer();
    await user.type(field, "/rev");
    await screen.findByRole("option", { name: /review/ });
    await user.keyboard("{ArrowDown}{Enter}");
    expect(field).toHaveValue("/review ");
    await user.type(field, 'shop-service "проверить возвраты"');
    await user.click(screen.getByRole("button", { name: "Отправить" }));
    expect(api.mutations()).toEqual([{
      method: "POST", path: "/tasks/t1/commands/run", body: {
        invocation: '/review shop-service "проверить возвраты"',
        client_request_id: expect.any(String),
      },
    }]);
  });

  test("предпросмотр использует командный endpoint", async ({ api }) => {
    api.respond("POST /tasks/t1/commands/preview", { rendered_text: "Проверь API" });
    const { user, field } = await openComposer();
    await user.type(field, "/review API");
    await user.click(screen.getByRole("button", { name: "Предпросмотр подстановки" }));
    await screen.findByText("Проверь API");
    expect(api.mutations()[0]).toEqual({method: "POST", path: "/tasks/t1/commands/preview", body: {invocation: "/review API"}});
  });

  test("неизвестная команда не отправляется агенту автоматически", async ({ api }) => {
    api.respond("POST /tasks/t1/commands/run", {error: {status: 404, message: "Команда не найдена"}});
    const { user, field } = await openComposer();
    await user.type(field, "/unknown text");
    await user.click(screen.getByRole("button", { name: "Отправить" }));
    const direct = await screen.findByRole("button", { name: "Отправить напрямую агенту" });
    expect(api.mutations()).toHaveLength(1);
    await user.click(direct);
    expect(api.mutations()[1]).toEqual({method: "POST", path: FREEFORM_PATH, body: {raw_prompt_text: "/unknown text"}});
  });

  test.for(["/plugin:review", "/compact Focus on the user's changes"])(
    "нативный вызов %s можно отправить буквально после проверки библиотеки", async (invocation, { api }) => {
      api.respond("POST /tasks/t1/commands/run", {error: {status: 404, message: "Команда не найдена"}});
      const { user, field } = await openComposer();
      await user.type(field, invocation);
      await user.click(screen.getByRole("button", {name: "Отправить"}));
      await user.click(await screen.findByRole("button", {name: "Отправить напрямую агенту"}));
      expect(api.mutations()[1]).toEqual({method: "POST", path: FREEFORM_PATH, body: {raw_prompt_text: invocation}});
    },
  );

  test("повтор запроса сохраняет идентификатор вызова", async ({ api }) => {
    api.respond("POST /tasks/t1/commands/run", {error: {status: 503, message: "Повторите запрос"}});
    const { user, field } = await openComposer();
    await user.type(field, "/review API");
    await user.click(screen.getByRole("button", { name: "Отправить" }));
    await expect.poll(() => screen.getByRole("button", { name: "Отправить" }).hasAttribute("disabled")).toBe(false);
    await user.click(screen.getByRole("button", { name: "Отправить" }));
    expect(api.mutations()).toHaveLength(2);
    expect(api.mutations()[0].body).toEqual(api.mutations()[1].body);
  });
});
