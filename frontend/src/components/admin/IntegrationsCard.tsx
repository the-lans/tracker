import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { LoadingState } from "@/components/common/feedback/LoadingState";
import { useIntegrations, useUpdateIntegrations } from "@/hooks/useAdmin";
import { toastError } from "@/lib/errors";
import type { Integrations } from "@/lib/types";

function IntegrationsForm({ initial }: { initial: Integrations }) {
  const [jiraUrl, setJiraUrl] = useState(initial.jira_url ?? "");
  const update = useUpdateIntegrations();

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    update.mutate(
      { jira_url: jiraUrl.trim() || null },
      {
        onSuccess: () => toast.success("Интеграции сохранены"),
        onError: toastError("Не удалось сохранить"),
      },
    );
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3">
      <div>
        <Label htmlFor="jira-server-url">Адрес Jira</Label>
        <Input
          id="jira-server-url"
          type="url"
          placeholder="https://company.atlassian.net"
          value={jiraUrl}
          onChange={(event) => setJiraUrl(event.target.value)}
        />
        <div className="mt-1 text-meta text-text-3">
          Сервер, из которого пользователи заполняют задачи по ключу. Личный токен каждый
          добавляет в профиле.
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={update.isPending}>
          Сохранить
        </Button>
      </div>
    </form>
  );
}

/**
 * Раздел 15.5, 15.6: адрес Jira для импорта задач — настройка системы, а не
 * переменная окружения. Доступ к GitLab API задаётся в «Учётные данные Git».
 */
export function IntegrationsCard() {
  const { data: integrations, isLoading } = useIntegrations();

  return (
    <Card className="text-body text-text-2">
      <div className="mb-3 text-body font-bold text-text">Интеграция с Jira</div>
      {isLoading && <LoadingState />}
      {integrations && <IntegrationsForm initial={integrations} />}
    </Card>
  );
}
