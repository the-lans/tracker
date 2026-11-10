import { describe, expect, test } from "vitest";
import { hasUsableAccount } from "@/lib/llmAccounts";
import { LlmLimitState } from "@/lib/types";
import { makeLlmAccount } from "@/test/factories";

describe("hasUsableAccount", () => {
  test.for([
    { owner: "u1", state: LlmLimitState.FREE, usable: true },
    { owner: "u1", state: LlmLimitState.AT_THRESHOLD, usable: true },
    { owner: "u1", state: LlmLimitState.EXCLUDED, usable: false },
    { owner: "u2", state: LlmLimitState.FREE, usable: false },
  ])("аккаунт $owner в состоянии $state → $usable", ({ owner, state, usable }) => {
    const accounts = [makeLlmAccount({ created_by: owner, limit_state: state })];

    expect(hasUsableAccount(accounts, "u1")).toBe(usable);
  });
});
