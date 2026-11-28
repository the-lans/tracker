import { useState } from "react";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { useProfile, useUpdateCiAgentModel } from "@/hooks/useProfile";
import { toastError } from "@/lib/errors";

export function CiAgentModelCard() {
  const { data: profile } = useProfile();
  const update = useUpdateCiAgentModel();
  const [draft, setDraft] = useState<string | null>(null);
  if (!profile) return null;
  const model = draft ?? profile.ci_agent_model;

  return (
    <Card>
      <form
        className="flex flex-col gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          update.mutate(
            { model: model.trim() },
            {
              onSuccess: () => setDraft(null),
              onError: toastError("Не удалось сохранить модель CI-агентов"),
            },
          );
        }}
      >
        <Label htmlFor="ci-agent-model">Модель для CI-агентов</Label>
        <div className="text-small text-text-3">
          Для обоих параллельных агентов: unit-тесты с линтерами и интеграционные тесты.
          Укажите идентификатор модели, доступной в ваших OpenAI-аккаунтах.
          Аккаунт с доступным лимитом выбирается автоматически.
        </div>
        <Input
          id="ci-agent-model"
          value={model}
          onChange={(event) => setDraft(event.target.value)}
          required
          maxLength={200}
          disabled={update.isPending}
        />
        <Button type="submit" disabled={update.isPending || !model.trim() || model.trim() === profile.ci_agent_model}>
          Сохранить
        </Button>
      </form>
    </Card>
  );
}
