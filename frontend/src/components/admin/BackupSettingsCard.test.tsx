import { screen, within } from "@testing-library/react";
import { describe, expect } from "vitest";
import { BackupSettingsCard } from "@/components/admin/BackupSettingsCard";
import { BackupRunStatus, type BackupSettings } from "@/lib/types";
import type { MockedApi } from "@/test/apiMock";
import { makeBackupRun, makeBackupSettings } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const PATH = "/system-settings/backup";

async function renderCard(api: MockedApi, settings: BackupSettings = makeBackupSettings()) {
  api.respond(`GET ${PATH}`, settings);
  api.respond(`PUT ${PATH}`, settings);
  const view = renderWithProviders(<BackupSettingsCard />);
  await screen.findByLabelText("Адрес S3");
  return view;
}

const SAVED = {
  enabled: true,
  endpoint: "https://s3.example.com",
  region: "ru-1",
  bucket: "tracker-backups",
  access_key: "AKEXAMPLE",
  secret_key: null,
  folder: "Tracker",
  retention_count: 7,
  passphrase: null,
};

describe("BackupSettingsCard: сохранение", () => {
  test("секреты не показываются — только признак, что сохранены", async ({ api }) => {
    await renderCard(api);

    for (const label of ["Секретный ключ (Secret Key)", "Пароль шифрования копий"]) {
      const field = screen.getByLabelText(label);
      expect(field).toHaveValue("");
      expect(field).toHaveAttribute("placeholder", "Сохранён — ввод заменит");
    }
  });

  test("без сохранённых секретов подсказки «Сохранён» нет", async ({ api }) => {
    await renderCard(api, makeBackupSettings({ secret_key_set: false, passphrase_set: false }));

    expect(screen.queryByPlaceholderText("Сохранён — ввод заменит")).not.toBeInTheDocument();
  });

  test.for([
    { name: "без правок секреты не отправляются", typed: {}, body: SAVED },
    {
      name: "введённые секреты уходят как есть",
      typed: { "Секретный ключ (Secret Key)": "new-secret", "Пароль шифрования копий": "долгий пароль 2026" },
      body: { ...SAVED, secret_key: "new-secret", passphrase: "долгий пароль 2026" },
    },
  ])("$name", async ({ typed, body }, { api, toasts }) => {
    const { user } = await renderCard(api);

    for (const [label, value] of Object.entries(typed)) {
      await user.type(screen.getByLabelText(label), value);
    }
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(api.mutations()).toEqual([{ method: "PUT", path: PATH, body }]);
    expect(toasts.success).toHaveBeenCalledWith("Настройки бэкапа сохранены");
  });

  test("пустые поля — null, папка и число копий как введены", async ({ api }) => {
    const { user } = await renderCard(api);

    await user.clear(screen.getByLabelText("Регион"));
    await user.clear(screen.getByLabelText("Папка в бакете"));
    await user.type(screen.getByLabelText("Папка в бакете"), " Tracker-prod ");
    await user.clear(screen.getByLabelText("Хранить копий"));
    await user.type(screen.getByLabelText("Хранить копий"), "14");
    await user.click(screen.getByRole("switch"));
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(api.mutations()[0]?.body).toEqual({
      ...SAVED,
      enabled: false,
      region: null,
      folder: "Tracker-prod",
      retention_count: 14,
    });
  });

  test("после сохранения поле секрета снова пустое", async ({ api }) => {
    const { user } = await renderCard(api);
    const field = screen.getByLabelText("Пароль шифрования копий");

    await user.type(field, "долгий пароль 2026");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    await expect.poll(() => field).toHaveValue("");
  });

  test("сохранённый пароль сразу отмечен по ответу сервера", async ({ api }) => {
    const { user } = await renderCard(api, makeBackupSettings({ passphrase_set: false }));
    api.respond(`PUT ${PATH}`, makeBackupSettings({ passphrase_set: true }));
    const field = screen.getByLabelText("Пароль шифрования копий");

    await user.type(field, "долгий пароль 2026");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    await expect.poll(() => field.getAttribute("placeholder")).toBe("Сохранён — ввод заменит");
  });

  test("ошибка сервера — в уведомлении", async ({ api, toasts }) => {
    const { user } = await renderCard(api);
    api.respond(`PUT ${PATH}`, {
      error: { status: 422, message: "Пароль шифрования — не короче 12 символов" },
    });

    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    await expect
      .poll(() => toasts.error.mock.calls[0]?.[0])
      .toContain("Пароль шифрования — не короче 12 символов");
  });
});

describe("BackupSettingsCard: проверка подключения", () => {
  test.for([
    { ok: true, message: "Подключение работает: запись и чтение прошли, папка Tracker уже есть" },
    { ok: false, message: "Доступ запрещён: проверьте ключи и права на бакет" },
  ])("ok=$ok — текст ответа под кнопкой", async ({ ok, message }, { api }) => {
    const { user } = await renderCard(api);
    api.respond(`POST ${PATH}/check`, { ok, message });

    await user.click(screen.getByRole("button", { name: "Проверить подключение" }));

    expect(await screen.findByRole("status")).toHaveTextContent(message);
    expect(api.mutations()).toEqual([{ method: "POST", path: `${PATH}/check`, body: undefined }]);
  });
});

describe("BackupSettingsCard: итоги запусков", () => {
  test("запусков не было", async ({ api }) => {
    await renderCard(api);

    expect(screen.getAllByText("ещё не запускался")).toHaveLength(2);
  });

  test.for([
    { status: BackupRunStatus.SUCCESS, label: "Успешно", extra: "tracker-backup-20261111T000000Z.tar.gpg" },
    { status: BackupRunStatus.RUNNING, label: "Выполняется", extra: "3 МБ" },
    { status: BackupRunStatus.FAILED, label: "Ошибка", extra: "Бакет не найден" },
  ])("бэкап $status → «$label»", async ({ status, label, extra }, { api }) => {
    await renderCard(
      api,
      makeBackupSettings({
        last_backup: makeBackupRun({
          status,
          error_message: status === BackupRunStatus.FAILED ? "Бакет не найден" : null,
        }),
      }),
    );

    const line = screen.getByText("Последний бэкап").parentElement?.parentElement;
    if (!line) throw new Error("строка бэкапа не найдена");
    expect(within(line).getByText(label)).toBeInTheDocument();
    expect(within(line).getByText(extra)).toBeInTheDocument();
  });

  test("пропущенные файлы перечислены", async ({ api }) => {
    await renderCard(
      api,
      makeBackupSettings({
        last_verify: makeBackupRun(),
        last_backup: makeBackupRun({
          status: BackupRunStatus.WARNING,
          skipped_files: [{ component: "task_repos", path: "RR-1/app/.git/index", reason: "locked" }],
        }),
      }),
    );

    expect(screen.getByText("С пропусками")).toBeInTheDocument();
    expect(screen.getByText(/Пропущено файлов: 1/)).toBeInTheDocument();
    expect(screen.getByText("task_repos/RR-1/app/.git/index")).toBeInTheDocument();
    expect(screen.queryByText("ещё не запускался")).not.toBeInTheDocument();
  });
});
