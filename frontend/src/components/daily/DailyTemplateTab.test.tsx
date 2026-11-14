import { screen } from "@testing-library/react";
import { describe, expect } from "vitest";
import { DailyTemplateTab } from "@/components/daily/DailyTemplateTab";
import type { MockedApi } from "@/test/apiMock";
import { makeDailyTemplate } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

function renderTemplate(api: MockedApi, isDefault = true) {
  api.respond("GET /daily/template", makeDailyTemplate({ content: "Сегодня:", is_default: isDefault }));
  return renderWithProviders(<DailyTemplateTab />);
}

describe("DailyTemplateTab", () => {
  test("переменные с подсказками", async ({ api }) => {
    renderTemplate(api);

    expect(await screen.findByText("{{daily.today}}")).toBeInTheDocument();
    expect(screen.getByText(/события дня, затем отмеченные задачи/)).toBeInTheDocument();
  });

  test("сохранение и предпросмотр — текущего текста", async ({ api }) => {
    api.respond("POST /daily/template/preview", { content: "Собранный план" });
    const { user } = renderTemplate(api);
    const text = await screen.findByLabelText("Текст шаблона");

    await user.type(text, " {{{{daily.today}}");
    await user.click(screen.getByRole("button", { name: "Предпросмотр" }));
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(await screen.findByText("Собранный план")).toBeInTheDocument();
    expect(api.mutations()).toEqual([
      { method: "POST", path: "/daily/template/preview", body: { content: "Сегодня: {{daily.today}}" } },
      { method: "PUT", path: "/daily/template", body: { content: "Сегодня: {{daily.today}}" } },
    ]);
  });

  test.for([
    { isDefault: true, disabled: true },
    { isDefault: false, disabled: false },
  ])("шаблон по умолчанию $isDefault → сброс недоступен $disabled", async ({ isDefault, disabled }, { api }) => {
    renderTemplate(api, isDefault);

    const reset = await screen.findByRole("button", { name: "Сбросить к шаблону по умолчанию" });

    expect(reset.hasAttribute("disabled")).toBe(disabled);
  });

  test("сброс — после подтверждения", async ({ api }) => {
    api.respond("DELETE /daily/template", makeDailyTemplate());
    const { user } = renderTemplate(api, false);

    await user.click(await screen.findByRole("button", { name: "Сбросить к шаблону по умолчанию" }));
    await user.click(screen.getByRole("button", { name: "Сбросить" }));

    expect(api.mutations()).toEqual([{ method: "DELETE", path: "/daily/template", body: undefined }]);
  });
});
