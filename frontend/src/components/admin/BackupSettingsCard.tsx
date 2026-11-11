import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { LoadingState } from "@/components/common/feedback/LoadingState";
import { BackupSettingsFields } from "@/components/admin/BackupSettingsFields";
import { BackupStatus } from "@/components/admin/BackupStatus";
import type { BackupForm } from "@/components/admin/backupSettings.types";
import {
  useBackupSettings,
  useCheckBackupConnection,
  useUpdateBackupSettings,
} from "@/hooks/useAdmin";
import { toastError } from "@/lib/errors";
import type { BackupConnectionCheck, BackupSettings, BackupSettingsUpdate } from "@/lib/types";
import { cn } from "@/lib/utils";

function initialForm(settings: BackupSettings): BackupForm {
  return {
    enabled: settings.enabled,
    endpoint: settings.endpoint ?? "",
    region: settings.region ?? "",
    bucket: settings.bucket ?? "",
    access_key: settings.access_key ?? "",
    secret_key: "",
    folder: settings.folder,
    retention_count: settings.retention_count,
    passphrase: "",
  };
}

function blankToNull(value: string): string | null {
  return value.trim() || null;
}

/** Пустой секрет не отправляется как пустая строка — сохранённый остаётся. */
function backupSettingsBody(form: BackupForm): BackupSettingsUpdate {
  return {
    enabled: form.enabled,
    endpoint: blankToNull(form.endpoint),
    region: blankToNull(form.region),
    bucket: blankToNull(form.bucket),
    access_key: blankToNull(form.access_key),
    secret_key: form.secret_key || null,
    folder: form.folder.trim(),
    retention_count: form.retention_count,
    passphrase: form.passphrase || null,
  };
}

function ConnectionResult({ check }: { check: BackupConnectionCheck }) {
  return (
    <div
      role="status"
      className={cn("break-words text-small", check.ok ? "text-success-text" : "text-danger-text")}
    >
      {check.message}
    </div>
  );
}

function BackupSettingsForm({ settings }: { settings: BackupSettings }) {
  const [form, setForm] = useState(() => initialForm(settings));
  const update = useUpdateBackupSettings();
  const check = useCheckBackupConnection();

  function patch(changes: Partial<BackupForm>) {
    setForm((prev) => ({ ...prev, ...changes }));
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    update.mutate(backupSettingsBody(form), {
      onSuccess: () => {
        toast.success("Настройки бэкапа сохранены");
        // Введённые секреты сохранены — поля снова означают «не менять».
        patch({ secret_key: "", passphrase: "" });
        check.reset();
      },
      onError: toastError("Не удалось сохранить настройки бэкапа"),
    });
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Label htmlFor="backup-enabled">Бэкап включён</Label>
          <div className="text-small text-text-3">
            Включить можно, когда заполнены все поля и задан пароль шифрования.
          </div>
        </div>
        <Switch
          id="backup-enabled"
          checked={form.enabled}
          onCheckedChange={(checked) => patch({ enabled: checked })}
        />
      </div>
      <BackupSettingsFields form={form} settings={settings} onChange={patch} />
      <div className="rounded-md bg-warning-tint p-3 text-small text-warning-text">
        Сохраните пароль шифрования вне сервера: без него копию не расшифровать. Смена пароля не
        перешифровывает уже загруженные копии — для них нужен прежний пароль.
      </div>
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={update.isPending}>
          Сохранить
        </Button>
        <Button
          type="button"
          variant="secondary"
          disabled={check.isPending}
          onClick={() => check.mutate(undefined, { onError: toastError("Проверка не выполнена") })}
        >
          {check.isPending ? "Проверка…" : "Проверить подключение"}
        </Button>
      </div>
      <div className="text-small text-text-3">
        Проверяются сохранённые настройки: запись, чтение и удаление пробного объекта, затем
        создаётся папка, если её нет.
      </div>
      {check.data && <ConnectionResult check={check.data} />}
    </form>
  );
}

/**
 * Раздел 15.5, 20.4: резервное копирование сервера в S3 — подключение, папка,
 * число хранимых копий, пароль шифрования и итоги последних запусков.
 */
export function BackupSettingsCard() {
  const { data: settings, isLoading } = useBackupSettings();

  return (
    <Card className="text-body text-text-2">
      <div className="mb-1 text-body font-bold text-text">Резервное копирование в S3</div>
      <div className="mb-3 text-small text-text-3">
        Каждую ночь — полная зашифрованная копия сервера: база, файлы и репозитории задач, данные
        агентов и .env. Раз в неделю последняя копия проверяется восстановлением.
      </div>
      {isLoading && <LoadingState />}
      {settings && (
        <div className="flex flex-col gap-3">
          <BackupSettingsForm settings={settings} />
          <BackupStatus lastBackup={settings.last_backup} lastVerify={settings.last_verify} />
        </div>
      )}
    </Card>
  );
}
