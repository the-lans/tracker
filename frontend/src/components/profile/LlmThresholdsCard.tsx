import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { Card, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { LoadingState } from "@/components/common/feedback/LoadingState";
import { useProfile, useUpdateLlmThresholds } from "@/hooks/useProfile";
import { toastError } from "@/lib/errors";
import type { User } from "@/lib/types";

// Раздел 19.7: порог — целое число процентов от 1 до 100.
const MIN_PCT = 1;
const MAX_PCT = 100;

function ThresholdField({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="flex-1">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type="number"
        min={MIN_PCT}
        max={MAX_PCT}
        step={1}
        required
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  );
}

function LlmThresholdsForm({ profile }: { profile: User }) {
  const [fiveHour, setFiveHour] = useState(String(profile.llm_switch_threshold_5h_pct));
  const [week, setWeek] = useState(String(profile.llm_switch_threshold_week_pct));
  const update = useUpdateLlmThresholds();

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    update.mutate(
      { five_hour_pct: Number(fiveHour), week_pct: Number(week) },
      {
        onSuccess: () => toast.success("Пороги переключения сохранены"),
        onError: toastError("Не удалось сохранить пороги"),
      },
    );
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3">
      <div className="flex gap-3">
        <ThresholdField id="threshold-5h" label="5-часовое окно, %" value={fiveHour} onChange={setFiveHour} />
        <ThresholdField id="threshold-week" label="Недельное окно, %" value={week} onChange={setWeek} />
      </div>
      <Button type="submit" className="self-start" disabled={update.isPending}>
        Сохранить
      </Button>
    </form>
  );
}

/**
 * Раздел 15.1, 19.7: расход окна лимита, на котором задача переходит на
 * следующий LLM-аккаунт по порядку.
 */
export function LlmThresholdsCard() {
  const { data: profile, isLoading } = useProfile();

  return (
    <Card>
      <CardTitle>
        <span>Переключение LLM-аккаунтов</span>
      </CardTitle>
      <div className="mb-3 text-small text-text-3">
        Когда расход окна лимита текущего аккаунта доходит до порога, следующее обращение задачи
        уходит на следующий аккаунт по порядку. Если все аккаунты выше порога, работа продолжается
        на наименее израсходованном.
      </div>
      {isLoading && <LoadingState />}
      {profile && <LlmThresholdsForm profile={profile} />}
    </Card>
  );
}
