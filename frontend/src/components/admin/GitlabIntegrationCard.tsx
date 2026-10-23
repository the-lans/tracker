import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { LoadingState } from "@/components/common/feedback/LoadingState";
import { useGitlabIntegration, useUpdateGitlabIntegration } from "@/hooks/useAdmin";
import { ApiError } from "@/lib/apiClient";
import type { GitlabIntegration } from "@/lib/types";

function GitlabIntegrationForm({ initial }: { initial: GitlabIntegration }) {
  const [url, setUrl] = useState(initial.gitlab_url ?? "");
  const [token, setToken] = useState("");
  const update = useUpdateGitlabIntegration();

  function save(gitlabToken: string | null) {
    update.mutate(
      { gitlab_url: url.trim() || null, gitlab_token: gitlabToken },
      {
        onSuccess: () => {
          setToken("");
          toast.success("Интеграция с GitLab сохранена");
        },
        onError: (error) =>
          toast.error(error instanceof ApiError ? error.message : "Не удалось сохранить"),
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
          value={url}
          onChange={(event) => setUrl(event.target.value)}
        />
      </div>
      <div>
        <Label htmlFor="gitlab-token">Токен API</Label>
        <Input
          id="gitlab-token"
          type="password"
          autoComplete="off"
          placeholder={initial.gitlab_token_set ? "Сохранён — введите новый, чтобы заменить" : ""}
          value={token}
          onChange={(event) => setToken(event.target.value)}
        />
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
            Удалить токен
          </Button>
        )}
      </div>
    </form>
  );
}

/**
 * Раздел 15.5, 16.2: адрес и токен GitLab API для синхронизации статусов MR.
 * Это настройка системы, а не переменная окружения: в промты и скрипты не
 * попадает, значение токена не показывается.
 */
export function GitlabIntegrationCard() {
  const { data: integration, isLoading } = useGitlabIntegration();

  return (
    <Card className="text-body text-text-2">
      <div className="mb-1 text-body font-bold text-text">Интеграция с GitLab</div>
      <div className="mb-3 text-small text-text-3">
        Нужна для синхронизации статусов merge request. Токен хранится зашифрованным и не
        показывается.
      </div>
      {isLoading && <LoadingState />}
      {integration && <GitlabIntegrationForm initial={integration} />}
    </Card>
  );
}
