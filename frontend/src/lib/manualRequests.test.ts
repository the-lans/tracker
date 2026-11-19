import { describe, expect, test } from "vitest";
import {
  isStoppableRequest,
  nextStoppableRequest,
  stopRequestLabel,
} from "@/lib/manualRequests";
import { ManualRequestStatus, ManualRequestType } from "@/lib/types";
import { makeManualRequest } from "@/test/factories";

const RUNNING = makeManualRequest({
  id: "run",
  status: ManualRequestStatus.PROCESSING,
});
const QUEUED_FREEFORM = makeManualRequest({ id: "free" });
const QUEUED_COMMAND = makeManualRequest({
  id: "cmd",
  command_name: "review",
  request_type: ManualRequestType.LIBRARY_PROMPT,
});

describe("isStoppableRequest", () => {
  test.for([
    { name: "выполняющийся свободный промт", request: RUNNING, expected: true },
    {
      name: "ожидающий свободный промт",
      request: QUEUED_FREEFORM,
      expected: false,
    },
    { name: "ожидающая команда", request: QUEUED_COMMAND, expected: true },
  ])("$name → $expected", ({ request, expected }) => {
    expect(isStoppableRequest(request)).toBe(expected);
  });
});

describe("nextStoppableRequest", () => {
  test("сначала выполняющийся, потом очередь", () => {
    expect(nextStoppableRequest([QUEUED_COMMAND, RUNNING])?.id).toBe("run");
    expect(nextStoppableRequest([QUEUED_COMMAND])?.id).toBe("cmd");
  });

  test("нечего останавливать — null", () => {
    expect(nextStoppableRequest([])).toBeNull();
    expect(nextStoppableRequest([QUEUED_FREEFORM])).toBeNull();
  });
});

describe("stopRequestLabel", () => {
  test.for([
    { request: RUNNING, label: "Остановить промт" },
    { request: QUEUED_COMMAND, label: "Отменить /review" },
    {
      request: { ...QUEUED_COMMAND, status: ManualRequestStatus.PROCESSING },
      label: "Остановить /review",
    },
  ])("$label", ({ request, label }) => {
    expect(stopRequestLabel(request)).toBe(label);
  });
});
