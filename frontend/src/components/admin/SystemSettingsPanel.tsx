import { useState, type FormEvent, type ReactNode } from "react";
import { toast } from "sonner";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useSystemSettings, useUpdateSystemSettings } from "@/hooks/useAdmin";
import { errorMessage } from "@/lib/errors";
import { parseIntegerInRange } from "@/lib/integerInput";
import { MAX_RETENTION_DAYS, RETENTION_FOREVER, type SystemSettings } from "@/lib/types";
import { TimeField } from "@/components/common/inputs/TimeField";
import { apiClockTime, clockTime } from "@/lib/clockTime";
import { cn } from "@/lib/utils";
import { CARD_DIVIDER } from "@/styles/classes";
import { LoadingState } from "@/components/common/feedback/LoadingState";
import { SectionTitle } from "@/components/common/typography/SectionTitle";
import { AppLogsRetentionField } from "@/components/admin/AppLogsRetentionField";
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

/** Группа полей формы под чертой: ночное окно, начало дня «Дейли». */
function SettingsFieldset({ legend, children }: { legend: string; children: ReactNode }) {
  return (
    <fieldset className={cn("mt-1 flex flex-col gap-2", CARD_DIVIDER)}>
      <legend className="text-body font-bold text-text">{legend}</legend>
      {children}
    </fieldset>
  );
}

function SettingsForm({ initial }: { initial: SystemSettings }) {
  const [values, setValues] = useState(initial);
  const update = useUpdateSystemSettings();
  const nightWindowEmpty =
    clockTime(values.night_window_start) === clockTime(values.night_window_end);
  // Черновик строкой: пустое поле не должно молча стать 0 — «бессрочно».
  const [appLogsDraft, setAppLogsDraft] = useState(String(initial.app_logs_retention_days));
  const appLogsDays = parseIntegerInRange(appLogsDraft, RETENTION_FOREVER, MAX_RETENTION_DAYS);

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!appLogsDays.valid) return;
    update.mutate({ ...values, app_logs_retention_days: appLogsDays.value }, {
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
      <SettingsFieldset legend="Ночной воркер, МСК">
        <div className="flex flex-wrap gap-3">
          {NIGHT_WINDOW_FIELDS.map(({ field, label }) => (
            <TimeField
              key={field}
              id={field}
              label={label}
              value={clockTime(values[field])}
              onChange={(value) => setValues((prev) => ({ ...prev, [field]: apiClockTime(value) }))}
              required
            />
          ))}
        </div>
        <div className={nightWindowEmpty ? "text-small text-danger-text" : "text-small text-text-3"}>
          {nightWindowEmpty
            ? "Начало и конец окна должны различаться"
            : "В начале окна ночной воркер запускает задачи «Ночной воркер»; окно может переходить через полночь. Начатые ночью задачи после конца окна не прерываются."}
        </div>
      </SettingsFieldset>
      {/* Раздел 15.8: с этого времени по МСК начинается день «Дейли»; с ночным окном не связано. */}
      <SettingsFieldset legend="Дейли, МСК">
        <TimeField
          id="day_start_time"
          label="Начало дня"
          value={clockTime(values.day_start_time)}
          onChange={(value) => setValues((prev) => ({ ...prev, day_start_time: apiClockTime(value) }))}
          required
        />
        <div className="text-small text-text-3">
          Отметки, события и работа по задачам до этого времени относятся к предыдущему дню. Сохранённые отметки и ручные события не пересчитываются.
        </div>
      </SettingsFieldset>
      <AppLogsRetentionField draft={appLogsDraft} parsed={appLogsDays} onChange={setAppLogsDraft} />
      <div>
        <Button type="submit" disabled={update.isPending || nightWindowEmpty || !appLogsDays.valid}>
          Сохранить
        </Button>
      </div>
    </form>
  );
}

/** Общие параметры выполнения, ночное окно, начало дня «Дейли», срок журнала, интеграции и бэкап в S3. */
export function SystemSettingsPanel() {
  const { data: settings, isLoading } = useSystemSettings();

  return (
    <div className="flex flex-col gap-2">
      <SectionTitle>
        Системные настройки
      </SectionTitle>
      <Card className="text-body text-text-2">
        <div className="mb-3 text-small text-text-3">
          Таймаут действует для всех запросов и нод, повторы — только для нод пайплайна. Изменения применяются со следующего запуска.
        </div>
        {isLoading && <LoadingState />}
        {settings && <SettingsForm initial={settings} />}
      </Card>
      <IntegrationsCard />
      <BackupSettingsCard />
    </div>
  );
}
