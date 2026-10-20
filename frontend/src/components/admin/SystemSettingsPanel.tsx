import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useSystemSettings, useUpdateSystemSettings } from "@/hooks/useAdmin";
import { ApiError } from "@/lib/apiClient";
import type { SystemSettings } from "@/lib/types";
import { LoadingState } from "@/components/common/feedback/LoadingState";
import { SectionTitle } from "@/components/common/typography/SectionTitle";

type NumericField =
  | "default_timeout_seconds"
  | "default_max_retries"
  | "default_retry_base_delay_seconds";
type TextField = "default_runner_image_python" | "default_runner_image_bash";

const NUMERIC_FIELDS: Array<{ field: NumericField; label: string }> = [
  { field: "default_timeout_seconds", label: "Таймаут ноды, сек." },
  { field: "default_max_retries", label: "Максимум попыток (retry)" },
  {
    field: "default_retry_base_delay_seconds",
    label: "Базовая задержка retry, сек.",
  },
];

const TEXT_FIELDS: Array<{ field: TextField; label: string }> = [
  { field: "default_runner_image_python", label: "Образ раннера Python" },
  { field: "default_runner_image_bash", label: "Образ раннера Bash" },
];

function SettingsForm({ initial }: { initial: SystemSettings }) {
  const [values, setValues] = useState(initial);
  const update = useUpdateSystemSettings();

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    update.mutate(values, {
      onSuccess: () => toast.success("Настройки сохранены"),
      onError: (error) =>
        toast.error(
          error instanceof ApiError
            ? error.message
            : "Не удалось сохранить настройки",
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
      {TEXT_FIELDS.map(({ field, label }) => (
        <div key={field}>
          <Label htmlFor={field}>{label}</Label>
          <Input
            id={field}
            value={values[field]}
            onChange={(event) =>
              setValues((prev) => ({ ...prev, [field]: event.target.value }))
            }
            required
          />
        </div>
      ))}
      <div>
        <Button type="submit" disabled={update.isPending}>
          Сохранить
        </Button>
      </div>
    </form>
  );
}

/** Раздел 15.5: значения по умолчанию для новых нод — уже созданные ноды не меняются. */
export function SystemSettingsPanel() {
  const { data: settings, isLoading } = useSystemSettings();

  return (
    <div className="flex flex-col gap-2">
      <SectionTitle>
        Системные настройки
      </SectionTitle>
      <Card className="text-body text-text-2">
        <div className="mb-3 text-small text-text-3">
          Значения подставляются в новые ноды; уже созданные ноды не меняются.
        </div>
        {isLoading && <LoadingState />}
        {settings && <SettingsForm initial={settings} />}
      </Card>
    </div>
  );
}
