import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { LlmLimitStateBadge } from "@/components/llmAccounts/LlmLimitStateBadge";
import { LlmLimitState } from "@/lib/types";
import { makeLlmAccount } from "@/test/factories";

const NOW = new Date(2026, 10, 10, 12, 0);

describe("LlmLimitStateBadge", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
  });
  afterEach(() => vi.useRealTimers());

  test("порог 5-часового окна: «На пороге · до ЧЧ:ММ»", () => {
    const until = new Date(2026, 10, 10, 15, 30).toISOString();
    render(
      <LlmLimitStateBadge
        account={makeLlmAccount({
          limit_state: LlmLimitState.AT_THRESHOLD,
          limit_state_until: until,
        })}
      />,
    );

    expect(screen.getByText("На пороге · до 15:30")).toBeInTheDocument();
  });

  test("порог недели: то же «На пороге», сброс — с датой", () => {
    const until = new Date(2026, 10, 14, 9, 0).toISOString();
    render(
      <LlmLimitStateBadge
        account={makeLlmAccount({
          limit_state: LlmLimitState.AT_THRESHOLD,
          limit_state_until: until,
        })}
      />,
    );

    expect(
      screen.getByText(/^На пороге · до 14 нояб\.?, 09:00$/),
    ).toBeInTheDocument();
  });

  test("число задач добавляется к состоянию", () => {
    render(
      <LlmLimitStateBadge
        account={makeLlmAccount({
          limit_state: LlmLimitState.AT_THRESHOLD,
          active_tasks: 2,
        })}
      />,
    );

    expect(screen.getByText("На пороге · 2 задачи")).toBeInTheDocument();
  });

  test("аккаунт вне выбора — бейджа нет", () => {
    const { container } = render(
      <LlmLimitStateBadge
        account={makeLlmAccount({ limit_state: LlmLimitState.EXCLUDED })}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
