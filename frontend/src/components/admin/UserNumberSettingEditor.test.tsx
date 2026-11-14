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

const USER = makeUser({
  id: "u2",
  max_parallel_tasks: 3,
  archive_after_days: 14,
  cleanup_repos_after_days: 0,
  artifacts_retention_days: 90,
});
const [ARCHIVE_SETTING, CLEANUP_SETTING, ARTIFACTS_SETTING] = RETENTION_SETTINGS;

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
    { setting: ARCHIVE_SETTING, input: "0{Enter}", body: { archive_after_days: 0 } },
    { setting: ARCHIVE_SETTING, input: "{Enter}", body: null },
    { setting: ARCHIVE_SETTING, input: "-1{Enter}", body: null },
    { setting: ARCHIVE_SETTING, input: "3651{Enter}", body: null },
    { setting: ARCHIVE_SETTING, input: "14{Enter}", body: null },
    { setting: CLEANUP_SETTING, input: "30{Enter}", body: { cleanup_repos_after_days: 30 } },
    { setting: CLEANUP_SETTING, input: "0{Enter}", body: null },
    { setting: ARTIFACTS_SETTING, input: "180{Enter}", body: { artifacts_retention_days: 180 } },
  ])("$setting.field: «$input» → $body", async ({ setting, input, body }, { api }) => {
    const { user } = renderEditor(setting);

    await user.clear(field(setting));
    await user.type(field(setting), input);

    expect(api.mutations()).toEqual(body ? [{ method: "PATCH", path: "/users/u2", body }] : []);
  });

  test.for([
    { setting: ARCHIVE_SETTING, value: 14, forever: false },
    { setting: CLEANUP_SETTING, value: 0, forever: true },
    { setting: ARTIFACTS_SETTING, value: 90, forever: false },
    { setting: MAX_PARALLEL_TASKS_SETTING, value: 3, forever: false },
  ])("$setting.field: значение $value, «бессрочно» — $forever", ({ setting, value, forever }) => {
    renderEditor(setting);

    expect(field(setting)).toHaveValue(value);
    expect(screen.queryByText("бессрочно") !== null).toBe(forever);
  });

  test.for([
    { setting: ARCHIVE_SETTING, forever: true },
    { setting: MAX_PARALLEL_TASKS_SETTING, forever: false },
  ])("$setting.field: набран 0 — «бессрочно» $forever", async ({ setting, forever }) => {
    const { user } = renderEditor(setting);

    await user.clear(field(setting));
    await user.type(field(setting), "0");

    expect(screen.queryByText("бессрочно") !== null).toBe(forever);
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
