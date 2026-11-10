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

function LlmThresholdForm({ profile }: { profile: User }) {
  const [fiveHour, setFiveHour] = useState(String(profile.llm_switch_threshold_5h_pct));
  const update = useUpdateLlmThresholds();

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    update.mutate(
      { five_hour_pct: Number(fiveHour) },
      {
        onSuccess: () => toast.success("Порог сохранён"),
        onError: toastError("Не удалось сохранить порог"),
      },
    );
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3">
      <div className="max-w-60">
        <Label htmlFor="threshold-5h">5-часовое окно, %</Label>
        <Input
          id="threshold-5h"
          type="number"
          min={MIN_PCT}
          max={MAX_PCT}
          step={1}
          required
          value={fiveHour}
          onChange={(event) => setFiveHour(event.target.value)}
        />
      </div>
      <Button type="submit" className="self-start" disabled={update.isPending}>
        Сохранить
      </Button>
    </form>
  );
}

/**
 * Раздел 15.1, 19.7: порог расхода 5-часового окна, который аккаунт не
 * переступает; неделя учитывается расходом и временем сброса, без порога.
 */
export function LlmThresholdsCard() {
  const { data: profile, isLoading } = useProfile();

  return (
    <Card>
      <CardTitle>
        <span>Порог LLM-аккаунтов</span>
      </CardTitle>
      <div className="mb-3 text-small text-text-3">
        Задачи распределяются по аккаунтам так, чтобы 5-часовые окна лимита стартовали по очереди,
        а расход окна не переступал порог. Если все аккаунты на пороге, задача ждёт ближайшего
        сброса в статусе «Ждёт лимита».
      </div>
      {isLoading && <LoadingState />}
      {profile && <LlmThresholdForm profile={profile} />}
    </Card>
  );
}
