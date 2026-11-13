import { useState } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  parseSetting,
  settingValue,
  type UserNumberSetting,
} from "@/components/admin/userNumberSettings";
import { useUpdateUser } from "@/hooks/useAdmin";
import { toastError } from "@/lib/errors";
import type { User } from "@/lib/types";

const OFF_PLACEHOLDER = "выкл.";

/**
 * Раздел 15.5: числовая настройка пользователя в строке администратора;
 * сохраняется по уходу с поля или Enter, Escape отменяет правку.
 */
export function UserNumberSettingEditor({ user, setting }: { user: User; setting: UserNumberSetting }) {
  const updateUser = useUpdateUser(user.id);
  const [draft, setDraft] = useState<string | null>(null);
  const current = settingValue(user, setting);
  const shown = draft ?? (current === null ? "" : String(current));
  const parsed = parseSetting(shown, setting);
  const inputId = `${setting.field}-${user.id}`;
  const range = `От ${setting.min} до ${setting.max}${setting.nullable ? "; пусто — выключено" : ""}`;

  function save() {
    if (draft === null) return;
    if (!parsed.valid || parsed.value === current) {
      setDraft(null);
      return;
    }
    updateUser.mutate(
      { [setting.field]: parsed.value },
      {
        onSettled: () => setDraft(null),
        onError: toastError(setting.errorMessage),
      },
    );
  }

  return (
    <div className="flex items-center gap-2 text-meta text-text-3">
      <Label htmlFor={inputId} className="text-meta font-normal text-text-3">
        {setting.label}:
      </Label>
      <Input
        id={inputId}
        type="number"
        inputMode="numeric"
        min={setting.min}
        max={setting.max}
        className="h-8 w-20"
        value={shown}
        placeholder={setting.nullable ? OFF_PLACEHOLDER : undefined}
        disabled={updateUser.isPending}
        aria-label={`${setting.label} ${user.email}`}
        aria-invalid={!parsed.valid}
        title={range}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={save}
        onKeyDown={(event) => {
          if (event.key === "Enter") save();
          if (event.key === "Escape") setDraft(null);
        }}
      />
    </div>
  );
}
