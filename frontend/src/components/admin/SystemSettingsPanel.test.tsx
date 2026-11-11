import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect } from "vitest";
import { SystemSettingsPanel } from "@/components/admin/SystemSettingsPanel";
import type { MockedApi } from "@/test/apiMock";
import { makeBackupSettings } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const SETTINGS = {
  default_timeout_seconds: 900,
  default_max_retries: 2,
  default_retry_base_delay_seconds: 10,
  night_window_start: "03:15:00",
  night_window_end: "07:00:00",
};

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
