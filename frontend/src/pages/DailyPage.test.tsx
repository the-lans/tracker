import { screen } from "@testing-library/react";
import { describe, expect } from "vitest";
import { DailyPage } from "@/pages/DailyPage";
import { makeDailyCalendar } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

describe("DailyPage", () => {
  test("вкладки «История», «Планы на день», «Шаблоны»; первая — по умолчанию", async ({ api }) => {
    api.respond("GET /daily/calendar", makeDailyCalendar());
    renderWithProviders(<DailyPage />, { path: "/daily" });

    const tabs = await screen.findAllByRole("tab", { name: /История|Планы на день|Шаблоны/ });
    expect(tabs.map((tab) => tab.textContent)).toEqual(["История", "Планы на день", "Шаблоны"]);
    expect(screen.getByRole("tab", { name: "История" })).toHaveAttribute("aria-selected", "true");
  });

  test.for([
    { tab: "plans", shown: "Новый план" },
    { tab: "templates", shown: "Предпросмотр" },
  ])("?tab=$tab открывает вкладку", async ({ tab, shown }, { api }) => {
    api.respond("GET /daily/calendar", makeDailyCalendar());
    api.respond("GET /daily/template", { content: "x", is_default: true, variables: [] });
    renderWithProviders(<DailyPage />, { path: `/daily?tab=${tab}` });

    expect(await screen.findByRole("button", { name: shown })).toBeInTheDocument();
  });
});
