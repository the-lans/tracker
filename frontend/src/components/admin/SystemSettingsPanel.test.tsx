import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect } from "vitest";
import { SystemSettingsPanel } from "@/components/admin/SystemSettingsPanel";
import type { MockedApi } from "@/test/apiMock";
import { makeBackupSettings, makeSystemSettings } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const SETTINGS = makeSystemSettings();

async function renderPanel(api: MockedApi) {
  api.respond("GET /system-settings", SETTINGS);
  api.respond("GET /system-settings/integrations", { jira_url: null });
  api.respond("GET /system-settings/backup", makeBackupSettings());
  const view = renderWithProviders(<SystemSettingsPanel />);
  await screen.findByLabelText("Начало");
  return view;
}

/** Поле `type="time"` в jsdom не принимает ввод с клавиатуры — значение задаётся событием. */
/** Кнопка формы настроек — у карточки интеграций своя «Сохранить». */
function saveButton() {
  const form = screen.getByLabelText("Начало").closest("form");
  if (!form) throw new Error("форма настроек не найдена");
  return within(form).getByRole("button", { name: "Сохранить" });
}

function setTime(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

describe("SystemSettingsPanel: ночное окно", () => {
  test.for([
    { start: "01:40", end: "06:00", saved: { night_window_start: "01:40:00", night_window_end: "06:00:00" } },
    { start: "23:30", end: "05:00", saved: { night_window_start: "23:30:00", night_window_end: "05:00:00" } },
  ])("$start–$end сохраняется вместе с настройками", async ({ start, end, saved }, { api }) => {
    const { user } = await renderPanel(api);

    setTime("Начало", start);
    setTime("Конец", end);
    await user.click(saveButton());

    expect(api.mutations()).toEqual([{ method: "PUT", path: "/system-settings", body: { ...SETTINGS, ...saved } }]);
  });

  test("начало и конец совпадают — сохранить нельзя", async ({ api }) => {
    await renderPanel(api);

    setTime("Начало", "07:00");

    expect(screen.getByText("Начало и конец окна должны различаться")).toBeInTheDocument();
    expect(saveButton()).toBeDisabled();
  });
});

describe("SystemSettingsPanel: хранение данных", () => {
  test.for([
    { input: "60", saved: 60, hint: "Записи журнала старше срока удаляются раз в день" },
    { input: "0", saved: 0, hint: "Журнал хранится бессрочно." },
  ])("срок журнала «$input» → $saved", async ({ input, saved, hint }, { api }) => {
    const { user } = await renderPanel(api);
    const field = screen.getByLabelText("Журнал приложения, дн.");

    await user.clear(field);
    await user.type(field, input);
    await user.click(saveButton());

    expect(screen.getByText(new RegExp(hint))).toBeInTheDocument();
    expect(api.mutations()).toEqual([
      { method: "PUT", path: "/system-settings", body: { ...SETTINGS, app_logs_retention_days: saved } },
    ]);
  });

  test.for(["", "2.5", "3651"])("срок журнала «%s» не сохраняется", async (input, { api }) => {
    const { user } = await renderPanel(api);
    const field = screen.getByLabelText("Журнал приложения, дн.");

    await user.clear(field);
    if (input) await user.type(field, input);

    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("Целое число от 0 до 3650")).toBeInTheDocument();
    expect(saveButton()).toBeDisabled();
    expect(api.mutations()).toEqual([]);
  });
});
