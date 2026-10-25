import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { Card, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ConfirmDeleteButton } from "@/components/common/actions/ConfirmDeleteButton";
import { LoadingState } from "@/components/common/feedback/LoadingState";
import {
  useDeleteJiraConnection,
  useJiraServer,
  useProfile,
  useUpdateJiraConnection,
} from "@/hooks/useProfile";
import { toastError } from "@/lib/errors";
import type { User } from "@/lib/types";

function JiraConnectionForm({ profile, serverUrl }: { profile: User; serverUrl: string }) {
  const [email, setEmail] = useState(profile.jira_email ?? "");
  const [token, setToken] = useState("");
  const update = useUpdateJiraConnection();
  const disconnect = useDeleteJiraConnection();

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    update.mutate(
      { jira_email: email.trim() || null, jira_token: token || null },
      {
        onSuccess: () => {
          setToken("");
          toast.success("Подключение к Jira сохранено");
        },
        onError: toastError("Не удалось сохранить"),
      },
    );
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3">
      <div className="text-small text-text-2">
        Сервер Jira: <span className="break-all font-mono">{serverUrl}</span>
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
            name={serverUrl}
            pending={disconnect.isPending}
            onConfirm={() =>
              disconnect.mutate(undefined, {
                onSuccess: () => setEmail(""),
              })
            }
          />
        )}
      </div>
    </form>
  );
}

/**
 * Раздел 15.6: личный доступ к Jira — для заполнения новой задачи по ключу.
 * Адрес Jira задаёт администратор в «Системных настройках».
 */
export function JiraConnectionCard() {
  const { data: profile, isLoading } = useProfile();
  const { data: server, isLoading: serverLoading } = useJiraServer();

  return (
    <Card>
      <CardTitle>
        <span>Jira</span>
      </CardTitle>
      <div className="mb-3 text-small text-text-3">
        Новую задачу можно заполнить из задачи Jira по ключу: код, название, описание, ссылка и
        вложения.
      </div>
      {(isLoading || serverLoading) && <LoadingState />}
      {server && !server.jira_url && (
        <div className="text-small text-text-3">
          Адрес Jira ещё не задан: его указывает администратор в «Системных настройках».
        </div>
      )}
      {profile && server?.jira_url && (
        <JiraConnectionForm profile={profile} serverUrl={server.jira_url} />
      )}
    </Card>
  );
}
