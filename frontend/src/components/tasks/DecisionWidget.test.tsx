import { screen } from "@testing-library/react";
import { describe, expect } from "vitest";
import { DecisionWidget } from "@/components/tasks/DecisionWidget";
import { NodeLogStatus, type NodeLog, type PendingOption } from "@/lib/types";
import { makeNodeLog, PLAN_OPTIONS } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const DECISION_PATH = "/tasks/t1/decision";

const QUESTION_OPTIONS: PendingOption[] = [
  { id: "0", label: "Оба способа сразу" },
  { id: "1", label: "Сначала только оплату картой" },
];

const TOOL_OPTIONS: PendingOption[] = [
  { id: "allow", label: "Разрешить" },
  { id: "deny", label: "Запретить" },
];

function awaitingLog(overrides: Partial<NodeLog>): NodeLog {
  return makeNodeLog({ status: NodeLogStatus.AWAITING_DECISION, finished_at: null, ...overrides });
}

const planLog = awaitingLog({
  pending_question: "План готов. Как продолжить?",
  pending_plan_text: "1. Кешировать ответ в Redis.\n2. Сбрасывать кеш при изменении заказа.",
  pending_options: PLAN_OPTIONS,
});

const questionLog = awaitingLog({
  pending_question: "Переводить на новый SDK оба способа оплаты сразу?",
  pending_options: QUESTION_OPTIONS,
});

const toolLog = awaitingLog({
  pending_question: "Агент хочет выполнить: rm -rf build",
  pending_options: TOOL_OPTIONS,
});

const openQuestionLog = awaitingLog({ pending_question: "Какой порт использовать для сервиса?" });

function renderWidget(log: NodeLog) {
  return renderWithProviders(<DecisionWidget taskId="t1" log={log} />);
}

describe("DecisionWidget", () => {
  describe("ревью плана", () => {
    test("показывает план, вопрос и три варианта решения", () => {
      renderWidget(planLog);

      expect(screen.getByText("План сформирован")).toBeInTheDocument();
      expect(screen.getByText("Кешировать ответ в Redis.")).toBeInTheDocument();
      expect(screen.getByText("План готов. Как продолжить?")).toBeInTheDocument();
      for (const option of PLAN_OPTIONS) {
        expect(screen.getByRole("button", { name: option.label })).toBeEnabled();
      }
    });

    test("длинный план показан целиком, без «Показать полностью»", () => {
      const longPlan = `${"1. Шаг плана.\n".repeat(40)}Последний шаг`;
      renderWidget(awaitingLog({ pending_plan_text: longPlan, pending_options: PLAN_OPTIONS }));

      expect(screen.getByText("Последний шаг")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Показать полностью →" })).not.toBeInTheDocument();
    });

    test.for(PLAN_OPTIONS)("«$label» отправляет вариант $id", async (option, { api }) => {
      const { user } = renderWidget(planLog);

      await user.click(screen.getByRole("button", { name: option.label }));

      expect(api.mutations()).toEqual([
        { method: "POST", path: DECISION_PATH, body: { node_log_id: "log1", option_id: option.id } },
      ]);
    });

    test("«Доработать план» отправляет комментарий", async ({ api }) => {
      const { user } = renderWidget(planLog);

      await user.type(screen.getByRole("textbox"), "Добавь метрику промахов");
      await user.click(screen.getByRole("button", { name: "Доработать план" }));

      expect(api.mutations()[0].body).toEqual({
        node_log_id: "log1",
        option_id: "revise",
        feedback_text: "Добавь метрику промахов",
      });
    });

    test("своего ответа нет — только варианты", () => {
      renderWidget(planLog);

      expect(screen.queryByRole("button", { name: /Ответить своим текстом/ })).not.toBeInTheDocument();
    });
  });

  describe("вопрос агента", () => {
    test("«Ответить своим текстом» неактивна, пока поле пустое", async () => {
      const { user } = renderWidget(questionLog);
      const answerButton = screen.getByRole("button", { name: /Ответить своим текстом/ });

      expect(answerButton).toBeDisabled();
      await user.type(screen.getByRole("textbox"), "   ");
      expect(answerButton).toBeDisabled();
    });

    test("свой ответ уходит как вариант custom", async ({ api }) => {
      const { user } = renderWidget(questionLog);

      await user.type(screen.getByRole("textbox"), "  Только СБП  ");
      await user.click(screen.getByRole("button", { name: /Ответить своим текстом/ }));

      expect(api.mutations()[0].body).toEqual({
        node_log_id: "log1",
        option_id: "custom",
        feedback_text: "Только СБП",
      });
    });

    test("выбранный вариант уходит вместе с комментарием", async ({ api }) => {
      const { user } = renderWidget(questionLog);

      await user.type(screen.getByRole("textbox"), "без миграции данных");
      await user.click(screen.getByRole("button", { name: "Сначала только оплату картой" }));

      expect(api.mutations()[0].body).toEqual({
        node_log_id: "log1",
        option_id: "1",
        feedback_text: "без миграции данных",
      });
    });

    test("вопрос без вариантов принимает открытый ответ", async ({ api }) => {
      const { user } = renderWidget(openQuestionLog);
      const sendButton = screen.getByRole("button");

      expect(sendButton).toBeDisabled();
      await user.type(screen.getByPlaceholderText("Ваш ответ…"), "8080");
      await user.click(sendButton);

      // Без вариантов backend читает ответ из option_id (plan_mode.answer_from_resolution).
      expect(api.mutations()[0].body).toEqual({ node_log_id: "log1", option_id: "8080" });
      expect(screen.getByPlaceholderText("Ваш ответ…")).toHaveValue("");
    });
  });

  describe("подтверждение действия", () => {
    test.for(TOOL_OPTIONS)("«$label» отправляет $id", async (option, { api }) => {
      const { user } = renderWidget(toolLog);

      expect(screen.getByText("Агент хочет выполнить: rm -rf build")).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: option.label }));

      expect(api.mutations()[0].body).toEqual({ node_log_id: "log1", option_id: option.id });
    });
  });

  describe("отправка решения", () => {
    test("пока решение отправляется, варианты неактивны", async ({ api }) => {
      api.respond(`POST ${DECISION_PATH}`, () => new Promise(() => {}));
      const { user } = renderWidget(planLog);

      await user.click(screen.getByRole("button", { name: PLAN_OPTIONS[0].label }));

      for (const option of PLAN_OPTIONS) {
        expect(screen.getByRole("button", { name: option.label })).toBeDisabled();
      }
      expect(api.mutations()).toHaveLength(1);
    });

    test("ошибка сервера показывается уведомлением", async ({ api, toasts }) => {
      api.respond(`POST ${DECISION_PATH}`, { error: { status: 409, message: "Решение уже принято" } });
      const { user } = renderWidget(planLog);

      await user.click(screen.getByRole("button", { name: PLAN_OPTIONS[0].label }));

      await expect.poll(() => toasts.error.mock.calls).toEqual([["Решение уже принято"]]);
    });
  });
});
