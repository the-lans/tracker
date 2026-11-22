import { describe, expect, it } from "vitest";
import { isInjectable, summarizeQueue } from "@/lib/manualQueue";
import { ManualRequestStatus, ManualRequestType } from "@/lib/types";
import { makeManualRequest } from "@/test/factories";

describe("isInjectable", () => {
  it.each([
    { name: "обычный текст", request: {}, expected: true },
    { name: "слэш-команда текстом", request: { raw_prompt_text: "  /compact" }, expected: false },
    { name: "команда библиотеки", request: { command_name: "review" }, expected: false },
    { name: "промт библиотеки", request: { request_type: ManualRequestType.LIBRARY_PROMPT }, expected: false },
    { name: "уже влит", request: { status: ManualRequestStatus.INJECTED }, expected: false },
  ])("$name → $expected", ({ request, expected }) => {
    expect(isInjectable(makeManualRequest(request))).toBe(expected);
  });
});

describe("summarizeQueue", () => {
  it("пустая очередь не показывается", () => {
    expect(summarizeQueue(undefined)).toEqual({ queued: 0, injectable: 0, injected: 0, shown: false });
  });

  it("считает ждущие, подходящие к влитию и влитые", () => {
    const summary = summarizeQueue([
      makeManualRequest({ id: "a" }),
      makeManualRequest({ id: "b", raw_prompt_text: "/compact" }),
      makeManualRequest({ id: "c", status: ManualRequestStatus.INJECTED }),
      makeManualRequest({ id: "d", status: ManualRequestStatus.PROCESSING }),
    ]);

    expect(summary).toEqual({ queued: 2, injectable: 1, injected: 1, shown: true });
  });

  it("одни влитые — индикатор показан, чтобы можно было отменить", () => {
    const summary = summarizeQueue([makeManualRequest({ status: ManualRequestStatus.INJECTED })]);

    expect(summary.shown).toBe(true);
    expect(summary.queued).toBe(0);
  });
});
