import { screen } from "@testing-library/react";
import { describe, expect } from "vitest";
import { LlmThresholdsCard } from "@/components/profile/LlmThresholdsCard";
import type { MockedApi } from "@/test/apiMock";
import { makeUser } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

function renderCard(api: MockedApi) {
  const profile = makeUser({ llm_switch_threshold_5h_pct: 93 });
  api.respond("GET /profile", profile);
  api.respond("PUT /profile/llm-thresholds", profile);
  return renderWithProviders(<LlmThresholdsCard />);
}

describe("LlmThresholdsCard", () => {
  test("показывает порог из профиля и только его", async ({ api }) => {
    renderCard(api);

    expect(await screen.findByLabelText("5-часовое окно, %")).toHaveValue(93);
    expect(screen.queryByLabelText(/Недельное окно/)).not.toBeInTheDocument();
  });

  test("сохраняет порог 5-часового окна", async ({ api, toasts }) => {
    const { user } = renderCard(api);

    const fiveHour = await screen.findByLabelText("5-часовое окно, %");
    await user.clear(fiveHour);
    await user.type(fiveHour, "80");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(api.mutations()).toEqual([
      { method: "PUT", path: "/profile/llm-thresholds", body: { five_hour_pct: 80 } },
    ]);
    expect(toasts.success).toHaveBeenCalledWith("Порог сохранён");
  });

  test.for(["0", "101", ""])("порог «%s» не отправляется", async (value, { api }) => {
    const { user } = renderCard(api);

    const fiveHour = await screen.findByLabelText("5-часовое окно, %");
    await user.clear(fiveHour);
    if (value) await user.type(fiveHour, value);
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(fiveHour).toBeInvalid();
    expect(api.mutations()).toEqual([]);
  });
});
