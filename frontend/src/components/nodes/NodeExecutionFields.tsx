import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { useSystemSettings } from "@/hooks/useAdmin";
import type { NodeExecutionValues } from "@/components/nodes/nodeForm.types";

/** Пустое поле — значение не задано: действует системное по умолчанию (оно в подсказке поля). */
function toOptionalNumber(raw: string): number | null {
  return raw === "" ? null : Number(raw);
}

/** Раздел 11.7, 15.5: таймаут, а у ноды пайплайна — retry и пропуск по умолчанию. */
export function NodeExecutionFields({
  values,
  withRetries,
  onChange,
}: {
  values: NodeExecutionValues;
  withRetries: boolean;
  onChange: (patch: Partial<NodeExecutionValues>) => void;
}) {
  const { data: settings } = useSystemSettings();

  return (
    <>
      <div>
        <Label htmlFor="node-timeout">Таймаут (сек.)</Label>
        <Input
          id="node-timeout"
          type="number"
          value={values.timeoutSeconds ?? ""}
          placeholder={settings?.default_timeout_seconds?.toString()}
          onChange={(e) => onChange({ timeoutSeconds: toOptionalNumber(e.target.value) })}
        />
      </div>

      {withRetries && (
        <>
          <div>
            <Label htmlFor="node-retries">Максимум попыток (retry)</Label>
            <Input
              id="node-retries"
              type="number"
              value={values.maxRetries ?? ""}
              placeholder={settings?.default_max_retries?.toString()}
              onChange={(e) => onChange({ maxRetries: toOptionalNumber(e.target.value) })}
            />
          </div>
          <div>
            <Label htmlFor="node-retry-delay">Базовая задержка retry (сек.)</Label>
            <Input
              id="node-retry-delay"
              type="number"
              min={0}
              value={values.retryBaseDelaySeconds ?? ""}
              placeholder={settings?.default_retry_base_delay_seconds?.toString()}
              onChange={(e) => onChange({ retryBaseDelaySeconds: toOptionalNumber(e.target.value) })}
            />
          </div>
          <label className="flex min-h-11 items-center gap-2.5 text-body font-semibold">
            <Checkbox
              checked={values.isSkipped}
              onCheckedChange={(checked) => onChange({ isSkipped: checked === true })}
            />
            Пропускать по умолчанию
          </label>
        </>
      )}
    </>
  );
}
