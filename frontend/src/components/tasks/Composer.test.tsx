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
}: { status?: TaskStatus; hasLlmAccount?: boolean } = {}) {
  return renderWithProviders(
    <Composer taskId="t1" taskStatus={status} hasLlmAccount={hasLlmAccount} />,
  );
}

async function openComposer() {
  const view = renderComposer();
  await view.user.click(screen.getByRole("button", { name: OPEN_COMPOSER }));
  return { ...view, field: screen.getByRole("textbox") };
}

describe("Composer", () => {
  describe("доступность", () => {
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

    test.for([TaskStatus.IN_PROGRESS, TaskStatus.NEW])(
      "%s без LLM-аккаунта: промт выполнить некому",
      (status) => {
        renderComposer({ status, hasLlmAccount: false });

        expect(
          screen.getByText("У задачи нет LLM-аккаунта — свободный промт выполнить некому"),
        ).toBeInTheDocument();
        expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
      },
    );
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
