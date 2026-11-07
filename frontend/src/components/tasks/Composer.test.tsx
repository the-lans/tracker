import { screen } from "@testing-library/react";
import { describe, expect } from "vitest";
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
  hasLlmAccount = true,
  manualRequestsClosed = false,
}: { status?: TaskStatus; hasLlmAccount?: boolean; manualRequestsClosed?: boolean } = {}) {
  return renderWithProviders(
    <Composer taskId="t1" taskStatus={status} hasLlmAccount={hasLlmAccount} manualRequestsClosed={manualRequestsClosed} />,
  );
}

async function openComposer() {
  const view = renderComposer();
  await view.user.click(screen.getByRole("button", { name: OPEN_COMPOSER }));
  return { ...view, field: screen.getByRole("textbox") };
}

describe("Composer", () => {
  describe("доступность", () => {
    test("финализация закрывает новый ввод, сохраняя управление принятыми вызовами", async ({ api }) => {
      api.respond("GET /tasks/t1/manual-queue", [makeManualRequest({command_name: "review"})]);
      const { user } = renderComposer({manualRequestsClosed: true});
      expect(screen.getByText("Задача завершается — приём новых промтов и команд закрыт")).toBeInTheDocument();
      expect(screen.queryByRole("button", {name: OPEN_COMPOSER})).not.toBeInTheDocument();
      await user.click(await screen.findByRole("button", {name: "Отменить /review"}));
      expect(api.mutations()[0].path).toBe("/tasks/t1/manual-queue/mq1/stop");
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
    ])("%s: промт можно написать", (status) => {
      renderComposer({ status });

      expect(screen.getByRole("button", { name: OPEN_COMPOSER })).toBeInTheDocument();
    });

    test.for([TaskStatus.NEW, TaskStatus.QUEUED, TaskStatus.FAILED, TaskStatus.DONE])(
      "%s: сессия не активна — поле закрыто с пояснением",
      (status) => {
        renderComposer({ status });

        expect(screen.getByText("Свободный промт доступен, пока сессия задачи активна")).toBeInTheDocument();
        expect(screen.queryByRole("button", { name: OPEN_COMPOSER })).not.toBeInTheDocument();
      },
    );

    test("без LLM-аккаунта в активной задаче доступны команды-скрипты", async () => {
      const { user } = renderComposer({ hasLlmAccount: false });
      await user.click(screen.getByRole("button", { name: OPEN_COMPOSER }));
      expect(screen.getByText("Без LLM-аккаунта доступны только команды-скрипты.")).toBeInTheDocument();
      await user.type(screen.getByRole("textbox"), "Обычный текст");
      expect(screen.getByRole("button", { name: "Отправить" })).toBeDisabled();
    });

    test("без LLM-аккаунта новая задача не принимает запросы", () => {
      renderComposer({ status: TaskStatus.NEW, hasLlmAccount: false });
      expect(screen.getByText("У задачи нет LLM-аккаунта — свободный промт выполнить некому")).toBeInTheDocument();
      expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    });

  });

  describe("отправка", () => {
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

  test("ожидающий вызов можно отменить из чата", async ({ api }) => {
    api.respond("GET /tasks/t1/manual-queue", [makeManualRequest({
      command_name: "review", command_revision: 2, request_type: ManualRequestType.LIBRARY_PROMPT,
    })]);
    const { user } = renderComposer();
    await user.click(await screen.findByRole("button", {name: "Отменить /review"}));
    expect(api.mutations()[0].path).toBe("/tasks/t1/manual-queue/mq1/stop");
  });
});
