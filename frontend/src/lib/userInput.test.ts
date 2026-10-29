import { describe, expect, it } from "vitest";
import { describeUserInput, splitOutputAtDecision, turnOutputOf } from "@/lib/userInput";
import { NodeLogStatus } from "@/lib/types";
import type { PendingOption } from "@/lib/types";
import { makeNodeLog, PLAN_OPTIONS } from "@/test/factories";

const QUESTION_OPTIONS: PendingOption[] = [
  { id: "0", label: "Оба способа сразу" },
  { id: "1", label: "Сначала только оплату картой" },
];
const PLAN = "1. Кнопка\n2. Тесты";

describe("describeUserInput", () => {
  it.each([
    {
      case: "вариант плана с комментарием",
      log: { pending_plan_text: PLAN, pending_options: PLAN_OPTIONS, user_input_text: "revise\nДобавь логирование" },
      view: { text: "Доработать план\n\nДобавь логирование", automatic: false },
    },
    {
      case: "автопринятие плана",
      log: { pending_plan_text: PLAN, pending_options: [], user_input_text: "accept_auto" },
      view: { text: "План принят автоматически", automatic: true },
    },
    {
      case: "«автоматически» выбрал сам пользователь",
      log: { pending_plan_text: PLAN, pending_options: PLAN_OPTIONS, user_input_text: "accept_auto" },
      view: { text: "Принять план и продолжить автоматически", automatic: false },
    },
    {
      case: "план без сохранённых вариантов, решение пользователя",
      log: { pending_plan_text: PLAN, pending_options: null, user_input_text: "accept_default" },
      view: { text: "Принять план, подтверждать каждое действие", automatic: false },
    },
    {
      case: "вариант вопроса",
      log: { pending_question: "Как платить?", pending_options: QUESTION_OPTIONS, user_input_text: "1" },
      view: { text: "Сначала только оплату картой", automatic: false },
    },
    {
      case: "свой ответ на вопрос с вариантами",
      log: { pending_question: "Как платить?", pending_options: QUESTION_OPTIONS, user_input_text: "custom\nТолько СБП" },
      view: { text: "Только СБП", automatic: false },
    },
    {
      case: "открытый вопрос — ответ целиком",
      log: { pending_question: "Какой порог?", pending_options: [], user_input_text: "50 МБ\nи не больше" },
      view: { text: "50 МБ\nи не больше", automatic: false },
    },
    {
      case: "id плана вне ревью плана не переводится",
      log: { pending_question: "Как назвать?", pending_options: [], user_input_text: "revise" },
      view: { text: "revise", automatic: false },
    },
  ])("$case", ({ log, view }) => {
    expect(describeUserInput(makeNodeLog(log))).toEqual(view);
  });
});

describe("splitOutputAtDecision", () => {
  it.each([
    { text: "Уточню.\n\nБерём dev.", offset: 7, before: "Уточню.", after: "Берём dev." },
    { text: "Берём dev.", offset: 0, before: "", after: "Берём dev." },
    { text: "Готово.", offset: null, before: "Готово.", after: "" },
    { text: "Готово.", offset: 7, before: "Готово.", after: "" },
    { text: "🙂 Вопрос\n\nОтвет", offset: 9, before: "🙂 Вопрос", after: "Ответ" },
  ])("«$text» по смещению $offset", ({ text, offset, before, after }) => {
    expect(splitOutputAtDecision(text, offset)).toEqual({ before, after });
  });
});

describe("turnOutputOf", () => {
  it.each([
    {
      name: "поток до решения",
      log: { status: NodeLogStatus.RUNNING },
      stream: "Читаю",
      view: { before: "Читаю", after: "", generating: true, liveAfterDecision: false, thinking: false },
    },
    {
      name: "ждёт решения",
      log: { status: NodeLogStatus.AWAITING_DECISION, decision_output_offset: 7 },
      stream: "Уточню.",
      view: { before: "Уточню.", after: "", generating: false, liveAfterDecision: false, thinking: false },
    },
    {
      name: "после решения, первый фрагмент ещё не пришёл",
      log: { status: NodeLogStatus.RUNNING, decision_output_offset: 7 },
      stream: "Уточню.",
      view: { before: "Уточню.", after: "", generating: true, liveAfterDecision: true, thinking: true },
    },
    {
      name: "итог заменяет поток",
      log: { status: NodeLogStatus.SUCCESS, llm_output_text: "Готово.", decision_output_offset: null },
      stream: "Гото",
      view: { before: "Готово.", after: "", generating: false, liveAfterDecision: false, thinking: false },
    },
    {
      name: "завершённая запись без итога поток не показывает",
      log: { status: NodeLogStatus.FAILED },
      stream: "Обрыв",
      view: { before: "", after: "", generating: false, liveAfterDecision: false, thinking: false },
    },
  ])("$name", ({ log, stream, view }) => {
    expect(turnOutputOf(makeNodeLog(log), stream, true)).toEqual({ ...view, keepExpanded: true });
  });

  it.each([
    { stream: undefined, agent: true, thinking: true, keepExpanded: false },
    { stream: undefined, agent: false, thinking: false, keepExpanded: false },
  ])("поток $stream, ход агента $agent → думает: $thinking", ({ stream, agent, thinking, keepExpanded }) => {
    const view = turnOutputOf(makeNodeLog({ status: NodeLogStatus.RUNNING }), stream, agent);

    expect({ thinking: view.thinking, keepExpanded: view.keepExpanded }).toEqual({ thinking, keepExpanded });
  });
});
