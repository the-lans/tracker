import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useSystemSettings, useUpdateSystemSettings } from "@/hooks/useAdmin";
import { errorMessage } from "@/lib/errors";
import type { SystemSettings } from "@/lib/types";
import { LoadingState } from "@/components/common/feedback/LoadingState";
import { SectionTitle } from "@/components/common/typography/SectionTitle";
import { IntegrationsCard } from "@/components/admin/IntegrationsCard";
import { BackupSettingsCard } from "@/components/admin/BackupSettingsCard";

type NumericField =
  | "default_timeout_seconds"
  | "default_max_retries"
  | "default_retry_base_delay_seconds";

const NUMERIC_FIELDS: Array<{ field: NumericField; label: string }> = [
  { field: "default_timeout_seconds", label: "Таймаут ноды, сек." },
  { field: "default_max_retries", label: "Максимум попыток (retry)" },
  {
    field: "default_retry_base_delay_seconds",
    label: "Базовая задержка retry, сек.",
  },
];

type NightWindowField = "night_window_start" | "night_window_end";

const NIGHT_WINDOW_FIELDS: Array<{ field: NightWindowField; label: string }> = [
  { field: "night_window_start", label: "Начало" },
  { field: "night_window_end", label: "Конец" },
];

/** «ЧЧ:ММ:СС» API ↔ «ЧЧ:ММ» поля `type="time"`. */
function clockTime(value: string): string {
  return value.slice(0, 5);
}

function SettingsForm({ initial }: { initial: SystemSettings }) {
  const [values, setValues] = useState(initial);
  const update = useUpdateSystemSettings();
  const nightWindowEmpty =
    clockTime(values.night_window_start) === clockTime(values.night_window_end);

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    update.mutate(values, {
      onSuccess: () => toast.success("Настройки сохранены"),
      onError: (error) =>
        toast.error(
          errorMessage(error, "Не удалось сохранить настройки"),
        ),
    });
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3">
      {NUMERIC_FIELDS.map(({ field, label }) => (
        <div key={field}>
          <Label htmlFor={field}>{label}</Label>
          <Input
            id={field}
            type="number"
            min={field === "default_retry_base_delay_seconds" ? 0 : 1}
            value={values[field]}
            onChange={(event) =>
              setValues((prev) => ({
                ...prev,
                [field]: Number(event.target.value),
              }))
            }
            required
          />
        </div>
      ))}
      {/* Раздел 14.4: окно ночного воркера; его начало задаёт расписание `dispatch_night_tasks`. */}
      <fieldset className="mt-1 flex flex-col gap-2 border-t border-border pt-3">
        <legend className="text-body font-bold text-text">Ночной воркер, МСК</legend>
        <div className="flex flex-wrap gap-3">
          {NIGHT_WINDOW_FIELDS.map(({ field, label }) => (
            <div key={field}>
              <Label htmlFor={field}>{label}</Label>
              <Input
                id={field}
                type="time"
                className="w-32"
                value={clockTime(values[field])}
                onChange={(event) =>
                  setValues((prev) => ({ ...prev, [field]: `${event.target.value}:00` }))
                }
                required
              />
            </div>
          ))}
        </div>
        <div className={nightWindowEmpty ? "text-small text-danger-text" : "text-small text-text-3"}>
          {nightWindowEmpty
            ? "Начало и конец окна должны различаться"
            : "В начале окна ночной воркер запускает задачи «Ночной воркер»; окно может переходить через полночь. Начатые ночью задачи после конца окна не прерываются."}
        </div>
      </fieldset>
      <div>
        <Button type="submit" disabled={update.isPending || nightWindowEmpty}>
          Сохранить
        </Button>
      </div>
    </form>
  );
}

/** Раздел 15.5: значения по умолчанию для новых нод (уже созданные не меняются), ночное окно, интеграции и бэкап в S3. */
export function SystemSettingsPanel() {
  const { data: settings, isLoading } = useSystemSettings();

  return (
    <div className="flex flex-col gap-2">
      <SectionTitle>
        Системные настройки
      </SectionTitle>
      <Card className="text-body text-text-2">
        <div className="mb-3 text-small text-text-3">
          Таймаут и retry подставляются в новые ноды; уже созданные ноды не меняются.
        </div>
        {isLoading && <LoadingState />}
        {settings && <SettingsForm initial={settings} />}
      </Card>
      <IntegrationsCard />
      <BackupSettingsCard />
    </div>
  );
}
