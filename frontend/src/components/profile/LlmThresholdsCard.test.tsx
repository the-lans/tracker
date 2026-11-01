import { screen } from "@testing-library/react";
import { describe, expect } from "vitest";
import { LlmThresholdsCard } from "@/components/profile/LlmThresholdsCard";
import type { MockedApi } from "@/test/apiMock";
import { makeUser } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

function renderCard(api: MockedApi) {
  const profile = makeUser({ llm_switch_threshold_5h_pct: 93, llm_switch_threshold_week_pct: 90 });
  api.respond("GET /profile", profile);
  api.respond("PUT /profile/llm-thresholds", profile);
  return renderWithProviders(<LlmThresholdsCard />);
}

describe("LlmThresholdsCard", () => {
  test("показывает пороги из профиля", async ({ api }) => {
    renderCard(api);

    expect(await screen.findByLabelText("5-часовое окно, %")).toHaveValue(93);
    expect(screen.getByLabelText("Недельное окно, %")).toHaveValue(90);
  });

  test("сохраняет оба порога", async ({ api, toasts }) => {
    const { user } = renderCard(api);

    const fiveHour = await screen.findByLabelText("5-часовое окно, %");
    await user.clear(fiveHour);
    await user.type(fiveHour, "80");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(api.mutations()).toEqual([
      { method: "PUT", path: "/profile/llm-thresholds", body: { five_hour_pct: 80, week_pct: 90 } },
    ]);
    expect(toasts.success).toHaveBeenCalledWith("Пороги переключения сохранены");
  });

  test.for(["0", "101", ""])("порог «%s» не отправляется", async (value, { api }) => {
    const { user } = renderCard(api);

    const week = await screen.findByLabelText("Недельное окно, %");
    await user.clear(week);
    if (value) await user.type(week, value);
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(week).toBeInvalid();
    expect(api.mutations()).toEqual([]);
  });
});
