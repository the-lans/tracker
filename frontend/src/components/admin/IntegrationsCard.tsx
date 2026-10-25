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
  const [gitlabUrl, setGitlabUrl] = useState(initial.gitlab_url ?? "");
  const [token, setToken] = useState("");
  const [jiraUrl, setJiraUrl] = useState(initial.jira_url ?? "");
  const update = useUpdateIntegrations();

  function save(gitlabToken: string | null) {
    update.mutate(
      {
        gitlab_url: gitlabUrl.trim() || null,
        gitlab_token: gitlabToken,
        jira_url: jiraUrl.trim() || null,
      },
      {
        onSuccess: () => {
          setToken("");
          toast.success("Интеграции сохранены");
        },
        onError: toastError("Не удалось сохранить"),
      },
    );
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    // Пустое поле токена — оставить сохранённый.
    save(token || null);
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3">
      <div>
        <Label htmlFor="gitlab-url">Адрес GitLab</Label>
        <Input
          id="gitlab-url"
          type="url"
          placeholder="https://gitlab.example.com"
          value={gitlabUrl}
          onChange={(event) => setGitlabUrl(event.target.value)}
        />
      </div>
      <div>
        <Label htmlFor="gitlab-token">Токен API GitLab</Label>
        <Input
          id="gitlab-token"
          type="password"
          autoComplete="off"
          placeholder={initial.gitlab_token_set ? "Сохранён — введите новый, чтобы заменить" : ""}
          value={token}
          onChange={(event) => setToken(event.target.value)}
        />
        <div className="mt-1 text-meta text-text-3">
          Нужен для синхронизации статусов merge request. Хранится зашифрованным и не
          показывается.
        </div>
      </div>
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
        {initial.gitlab_token_set && (
          <Button
            type="button"
            variant="secondary"
            disabled={update.isPending}
            onClick={() => save("")}
          >
            Удалить токен GitLab
          </Button>
        )}
      </div>
    </form>
  );
}

/**
 * Раздел 15.5, 15.6, 16.2: адрес и токен GitLab API для синхронизации статусов
 * MR и адрес Jira для импорта задач. Это настройки системы, а не переменные
 * окружения: в промты и скрипты не попадают, значение токена не показывается.
 */
export function IntegrationsCard() {
  const { data: integrations, isLoading } = useIntegrations();

  return (
    <Card className="text-body text-text-2">
      <div className="mb-3 text-body font-bold text-text">Интеграции: GitLab и Jira</div>
      {isLoading && <LoadingState />}
      {integrations && <IntegrationsForm initial={integrations} />}
    </Card>
  );
}
