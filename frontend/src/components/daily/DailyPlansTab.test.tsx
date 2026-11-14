import { screen } from "@testing-library/react";
import { describe, expect } from "vitest";
import { DailyPlansTab } from "@/components/daily/DailyPlansTab";
import type { MockedApi } from "@/test/apiMock";
import { makeDailyCalendar, makeDailyPlan } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

function renderPlans(api: MockedApi, plans = [makeDailyPlan({ id: "p1", day: "2026-11-16", content: "План" })]) {
  api.respond("GET /daily/plans", plans);
  return renderWithProviders(<DailyPlansTab calendar={makeDailyCalendar()} />);
}

describe("DailyPlansTab", () => {
  test("без планов — подсказка, новый план — на сегодня", async ({ api }) => {
    api.respond("POST /daily/plans", makeDailyPlan());
    const { user } = renderPlans(api, []);

    expect(await screen.findByText("Планов пока нет")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Новый план" }));

    expect(api.mutations()).toEqual([{ method: "POST", path: "/daily/plans", body: { day: "2026-11-16" } }]);
  });

  test("день с планом не предлагается — по умолчанию следующий свободный", async ({ api }) => {
    api.respond("POST /daily/plans", makeDailyPlan({ id: "p2", day: "2026-11-17" }));
    const { user } = renderPlans(api);
    await screen.findByLabelText("Текст плана");

    await user.click(screen.getByRole("button", { name: "Новый план" }));

    expect(api.mutations()).toEqual([{ method: "POST", path: "/daily/plans", body: { day: "2026-11-17" } }]);
  });

  test("правка сохраняется только после изменения", async ({ api }) => {
    const { user } = renderPlans(api);
    const text = await screen.findByLabelText("Текст плана");
    expect(screen.getByRole("button", { name: "Сохранить" })).toBeDisabled();

    await user.type(text, " дополнен");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(api.mutations()).toEqual([
      { method: "PUT", path: "/daily/plans/p1", body: { content: "План дополнен" } },
    ]);
  });

  test("пересборка — только после подтверждения", async ({ api }) => {
    api.respond("POST /daily/plans/p1/regenerate", makeDailyPlan({ content: "Заново" }));
    const { user } = renderPlans(api);

    await user.click(await screen.findByRole("button", { name: "Пересобрать по шаблону" }));
    expect(api.mutations()).toEqual([]);
    await user.click(screen.getByRole("button", { name: "Пересобрать" }));

    expect(api.mutations()).toEqual([{ method: "POST", path: "/daily/plans/p1/regenerate", body: undefined }]);
  });
});
