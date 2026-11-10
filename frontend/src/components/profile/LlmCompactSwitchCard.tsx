import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useProfile, useUpdateLlmCompact } from "@/hooks/useProfile";
import { toastError } from "@/lib/errors";

/**
 * Раздел 15.1, 19.7: перед ходом на новом LLM-аккаунте контекст сессии
 * сжимается командой `/compact` на прежнем аккаунте.
 */
export function LlmCompactSwitchCard() {
  const { data: profile } = useProfile();
  const update = useUpdateLlmCompact();

  if (!profile) return null;
  return (
    <Card>
      <div className="flex items-start justify-between gap-3">
        <div>
          <Label htmlFor="llm-compact-on-switch" className="text-body font-bold">
            Сжимать контекст при смене LLM-аккаунта
          </Label>
          <div className="mt-1 text-small text-text-3">
            Перед первым ходом на новом аккаунте сессия выполняет /compact на прежнем: новый
            аккаунт получает сжатую историю вместо полной.
          </div>
        </div>
        <Switch
          id="llm-compact-on-switch"
          checked={profile.llm_compact_on_switch}
          disabled={update.isPending}
          onCheckedChange={(enabled) =>
            update.mutate({ enabled }, { onError: toastError("Не удалось сохранить настройку") })
          }
        />
      </div>
    </Card>
  );
}
