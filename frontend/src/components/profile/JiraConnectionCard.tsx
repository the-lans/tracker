import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { Card, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ConfirmDeleteButton } from "@/components/common/actions/ConfirmDeleteButton";
import { LoadingState } from "@/components/common/feedback/LoadingState";
import { useDeleteJiraConnection, useProfile, useUpdateJiraConnection } from "@/hooks/useProfile";
import { ApiError } from "@/lib/apiClient";
import type { User } from "@/lib/types";

function JiraConnectionForm({ profile }: { profile: User }) {
  const [url, setUrl] = useState(profile.jira_url ?? "");
  const [email, setEmail] = useState(profile.jira_email ?? "");
  const [token, setToken] = useState("");
  const update = useUpdateJiraConnection();
  const disconnect = useDeleteJiraConnection();

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    update.mutate(
      { jira_url: url.trim(), jira_email: email.trim() || null, jira_token: token || null },
      {
        onSuccess: () => {
          setToken("");
          toast.success("Подключение к Jira сохранено");
        },
        onError: (error) =>
          toast.error(error instanceof ApiError ? error.message : "Не удалось сохранить"),
      },
    );
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3">
      <div>
        <Label htmlFor="jira-url">Адрес Jira</Label>
        <Input
          id="jira-url"
          type="url"
          placeholder="https://company.atlassian.net"
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          required
        />
      </div>
      <div>
        <Label htmlFor="jira-email">Email в Jira Cloud</Label>
        <Input
          id="jira-email"
          type="email"
          placeholder="Пусто — для Jira Server/Data Center"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
      </div>
      <div>
        <Label htmlFor="jira-token">Личный токен</Label>
        <Input
          id="jira-token"
          type="password"
          autoComplete="off"
          placeholder={profile.jira_token_set ? "Сохранён — введите новый, чтобы заменить" : ""}
          value={token}
          onChange={(event) => setToken(event.target.value)}
          required={!profile.jira_token_set}
        />
        <div className="mt-1 text-meta text-text-3">
          Jira Cloud — API token из настроек учётной записи Atlassian; Jira Server/Data Center —
          personal access token. Хранится зашифрованным и не показывается.
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" disabled={update.isPending}>
          Сохранить
        </Button>
        {profile.jira_token_set && (
          <ConfirmDeleteButton
            kind="подключение к Jira"
            name={profile.jira_url ?? "Jira"}
            pending={disconnect.isPending}
            onConfirm={() =>
              disconnect.mutate(undefined, {
                onSuccess: () => {
                  setUrl("");
                  setEmail("");
                },
              })
            }
          />
        )}
      </div>
    </form>
  );
}

/** Раздел 15.6: личное подключение к Jira — для заполнения новой задачи по ключу. */
export function JiraConnectionCard() {
  const { data: profile, isLoading } = useProfile();

  return (
    <Card>
      <CardTitle>
        <span>Jira</span>
      </CardTitle>
      <div className="mb-3 text-small text-text-3">
        Новую задачу можно заполнить из задачи Jira по ключу: код, название, описание, ссылка и
        вложения.
      </div>
      {isLoading && <LoadingState />}
      {profile && <JiraConnectionForm profile={profile} />}
    </Card>
  );
}
