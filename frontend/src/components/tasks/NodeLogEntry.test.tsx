import { screen } from "@testing-library/react";
import { describe, expect } from "vitest";
import { NodeLogEntry } from "@/components/tasks/NodeLogEntry";
import { NodeLogStatus, NodeLogTriggerType, type NodeLog } from "@/lib/types";
import { makeNodeLog, PLAN_OPTIONS } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const PLAN = "1. Добавить кнопку\n2. Написать тесты";

function renderEntry(log: Partial<NodeLog>, { title, streamedText }: { title?: string; streamedText?: string } = {}) {
  return renderWithProviders(
    <NodeLogEntry taskId="t1" log={makeNodeLog(log)} title={title} streamedText={streamedText} />,
  );
}

describe("NodeLogEntry", () => {
  describe("заголовок записи", () => {
    test.for([
      { trigger: NodeLogTriggerType.PIPELINE, nodeId: "n1", heading: "Реализация" },
      { trigger: NodeLogTriggerType.PIPELINE, nodeId: null, heading: "Разрешение конфликта ребейза · Реализация" },
      { trigger: NodeLogTriggerType.FREEFORM_MANUAL, nodeId: null, heading: "Отправлено вручную · Реализация" },
      { trigger: NodeLogTriggerType.LIBRARY_MANUAL, nodeId: "l1", heading: "Промт из библиотеки · Реализация" },
      { trigger: NodeLogTriggerType.SUMMARY_FOR_CHILD, nodeId: null, heading: "Пересказ для дочерней задачи · Реализация" },
      { trigger: NodeLogTriggerType.PARENT_SUMMARY, nodeId: null, heading: "Саммари родительской задачи · Реализация" },
    ])("$trigger, нода $nodeId → «$heading»", ({ trigger, nodeId, heading }) => {
      renderEntry({ trigger_type: trigger, node_id: nodeId }, { title: "Реализация" });

      expect(screen.getByTitle(heading)).toHaveTextContent(heading);
    });

    test("без названия — «Нода пайплайна»", () => {
      renderEntry({});

      expect(screen.getByTitle("Нода пайплайна")).toBeInTheDocument();
    });
  });

  describe("решение пользователя в ответе", () => {
    test.for([
      { offset: 7, order: ["Уточню.", "main", "Берём базу."] },
      { offset: null, order: ["Уточню.", "Берём базу.", "main"] },
    ])("смещение $offset → порядок $order", ({ offset, order }) => {
      const { container } = renderEntry({
        llm_output_text: "Уточню.\n\nБерём базу.",
        decision_output_offset: offset,
        user_input_text: "0",
        pending_question: "Какую базу?",
        pending_options: [
          { id: "0", label: "main" },
          { id: "1", label: "dev" },
        ],
      });

      const text = container.textContent ?? "";
      const positions = order.map((part) => text.indexOf(part));
      expect(positions.every((position) => position >= 0)).toBe(true);
      expect(positions).toEqual([...positions].sort((a, b) => a - b));
    });
  });

  describe("содержимое", () => {
    test("скрипт показывает вывод, а не текст промта", () => {
      const { container } = renderEntry({
        rendered_prompt: "pytest -q",
        script_stdout: "5 passed",
        script_exit_code: 0,
      });

      expect(container).toHaveTextContent("ВЫВОД СКРИПТА");
      expect(container).toHaveTextContent("5 passed");
      expect(container).not.toHaveTextContent("pytest -q");
    });

    test.for([
      { status: NodeLogStatus.RUNNING, output: null, shown: "Добавляю кно", live: true },
      { status: NodeLogStatus.RUNNING, output: "Готово: кнопка добавлена", shown: "Готово: кнопка добавлена", live: false },
      { status: NodeLogStatus.SUCCESS, output: null, shown: null, live: false },
    ])("$status, итог «$output» → видно «$shown»", ({ status, output, shown, live }) => {
      renderEntry({ status, llm_output_text: output }, { streamedText: "Добавляю кно" });

      if (shown) expect(screen.getByText(shown)).toBeInTheDocument();
      if (shown !== "Добавляю кно") expect(screen.queryByText("Добавляю кно")).not.toBeInTheDocument();
      expect(screen.queryByText("генерируется…") !== null).toBe(live);
    });

    test.for([
      { status: NodeLogStatus.FAILED, trigger: NodeLogTriggerType.PIPELINE, output: null, text: "Ошибка выполнения (попытка 3)" },
      { status: NodeLogStatus.STOPPED, trigger: NodeLogTriggerType.PIPELINE, output: null, text: "Остановлено пользователем" },
    ])("$status → «$text»", ({ status, trigger, output, text }) => {
      renderEntry({ status, trigger_type: trigger, llm_output_text: output, attempt_number: 3 });

      expect(screen.getByText(text)).toBeInTheDocument();
    });

    test("недоступное саммари родителя — без общей ошибки", () => {
      renderEntry({
        status: NodeLogStatus.FAILED,
        trigger_type: NodeLogTriggerType.PARENT_SUMMARY,
        node_id: null,
        llm_output_text: null,
      });

      expect(screen.queryByText(/Ошибка выполнения/)).not.toBeInTheDocument();
    });
  });

  describe("план и решение", () => {
    test("ждёт решения — виджет решения, без ответа пользователя", () => {
      renderEntry({
        status: NodeLogStatus.AWAITING_DECISION,
        pending_plan_text: PLAN,
        pending_options: PLAN_OPTIONS,
        user_input_text: "revise\nСтарый комментарий",
      });

      expect(screen.getByRole("button", { name: "Принять план и продолжить автоматически" })).toBeInTheDocument();
      expect(screen.queryByText(/Старый комментарий/)).not.toBeInTheDocument();
    });

    test.for([
      { input: "accept_auto", options: [], decision: "План принят автоматически" },
      { input: "accept_default", options: PLAN_OPTIONS, decision: "Принять план, подтверждать каждое действие" },
      { input: "accept_auto\nДобавь логирование", options: PLAN_OPTIONS, decision: "Добавь логирование" },
    ])("принятый план и решение «$input»", ({ input, options, decision }) => {
      const { container } = renderEntry({
        status: NodeLogStatus.SUCCESS,
        pending_plan_text: PLAN,
        pending_options: options,
        user_input_text: input,
      });

      expect(container).toHaveTextContent("План принят.");
      expect(container).toHaveTextContent("Добавить кнопку");
      expect(container).toHaveTextContent(decision);
    });
  });
});
