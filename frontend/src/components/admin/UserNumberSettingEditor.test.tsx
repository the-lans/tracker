import { screen } from "@testing-library/react";
import { describe, expect } from "vitest";
import { UserNumberSettingEditor } from "@/components/admin/UserNumberSettingEditor";
import {
  MAX_PARALLEL_TASKS_SETTING,
  RETENTION_SETTINGS,
  type UserNumberSetting,
} from "@/components/admin/userNumberSettings";
import { makeUser } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const USER = makeUser({ id: "u2", max_parallel_tasks: 3, archive_after_days: 14, cleanup_repos_after_days: null });
const [ARCHIVE_SETTING, CLEANUP_SETTING] = RETENTION_SETTINGS;

const field = (setting: UserNumberSetting) =>
  screen.getByRole("spinbutton", { name: `${setting.label} ${USER.email}` });

function renderEditor(setting: UserNumberSetting) {
  return renderWithProviders(<UserNumberSettingEditor user={USER} setting={setting} />);
}

describe("UserNumberSettingEditor", () => {
  test.for([
    { setting: MAX_PARALLEL_TASKS_SETTING, input: "5{Enter}", body: { max_parallel_tasks: 5 } },
    { setting: MAX_PARALLEL_TASKS_SETTING, input: "50{Enter}", body: { max_parallel_tasks: 50 } },
    { setting: MAX_PARALLEL_TASKS_SETTING, input: "1{Enter}", body: { max_parallel_tasks: 1 } },
    { setting: MAX_PARALLEL_TASKS_SETTING, input: "0{Enter}", body: null },
    { setting: MAX_PARALLEL_TASKS_SETTING, input: "51{Enter}", body: null },
    { setting: MAX_PARALLEL_TASKS_SETTING, input: "3{Enter}", body: null },
    { setting: MAX_PARALLEL_TASKS_SETTING, input: "{Enter}", body: null },
    { setting: MAX_PARALLEL_TASKS_SETTING, input: "7{Escape}", body: null },
    { setting: ARCHIVE_SETTING, input: "3650{Enter}", body: { archive_after_days: 3650 } },
    { setting: ARCHIVE_SETTING, input: "{Enter}", body: { archive_after_days: null } },
    { setting: ARCHIVE_SETTING, input: "3651{Enter}", body: null },
    { setting: ARCHIVE_SETTING, input: "14{Enter}", body: null },
    { setting: CLEANUP_SETTING, input: "30{Enter}", body: { cleanup_repos_after_days: 30 } },
    { setting: CLEANUP_SETTING, input: "{Enter}", body: null },
  ])("$setting.field: «$input» → $body", async ({ setting, input, body }, { api }) => {
    const { user } = renderEditor(setting);

    await user.clear(field(setting));
    await user.type(field(setting), input);

    expect(api.mutations()).toEqual(body ? [{ method: "PATCH", path: "/users/u2", body }] : []);
  });

  test.for([
    { setting: ARCHIVE_SETTING, value: 14, placeholder: "выкл." },
    { setting: CLEANUP_SETTING, value: null, placeholder: "выкл." },
    { setting: MAX_PARALLEL_TASKS_SETTING, value: 3, placeholder: null },
  ])("$setting.field: значение $value, подсказка $placeholder", ({ setting, value, placeholder }) => {
    renderEditor(setting);

    expect(field(setting)).toHaveValue(value);
    expect(field(setting).getAttribute("placeholder")).toBe(placeholder);
  });

  test("Escape отменяет правку — уход с поля ничего не сохраняет", async ({ api }) => {
    const { user } = renderEditor(MAX_PARALLEL_TASKS_SETTING);

    await user.clear(field(MAX_PARALLEL_TASKS_SETTING));
    await user.type(field(MAX_PARALLEL_TASKS_SETTING), "8{Escape}");
    await user.tab();

    expect(api.mutations()).toEqual([]);
    expect(field(MAX_PARALLEL_TASKS_SETTING)).toHaveValue(3);
  });

  test("сохраняется и по уходу с поля", async ({ api }) => {
    const { user } = renderEditor(ARCHIVE_SETTING);

    await user.clear(field(ARCHIVE_SETTING));
    await user.type(field(ARCHIVE_SETTING), "8");
    await user.tab();

    expect(api.mutations()).toEqual([{ method: "PATCH", path: "/users/u2", body: { archive_after_days: 8 } }]);
  });

});
