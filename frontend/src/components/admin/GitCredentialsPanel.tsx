import { useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card } from "@/components/ui/card";
import { DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { EntityFormDialog, type EditTarget } from "@/components/common/dialogs/EntityFormDialog";
import { ConfirmDeleteButton } from "@/components/common/actions/ConfirmDeleteButton";
import { EditButton } from "@/components/common/actions/EditButton";
import { LoadingState } from "@/components/common/feedback/LoadingState";
import { SectionTitle } from "@/components/common/typography/SectionTitle";
import {
  useGitCredentials, useSaveGitCredential, useDeleteGitCredential, type GitCredential,
} from "@/hooks/useGitCredentials";
import { GitlabApiFields } from "@/components/admin/GitlabApiFields";
import type { GitCredentialCheck, GitlabApiState } from "@/components/admin/gitCredentials.types";
import { api } from "@/lib/apiClient";
import { errorMessage, toastError } from "@/lib/errors";
import {
  GITLAB_API_OK, gitlabApiBody, gitlabApiCheckMessage, gitlabApiTokenMissing, initialGitlabApi,
} from "@/lib/gitlabApi";

function CredentialForm({ credential, onSaved }: { credential?: GitCredential; onSaved: () => void }) {
  const [name, setName] = useState(credential?.name ?? "");
  const [host, setHost] = useState(credential?.host ?? "");
  const [kind, setKind] = useState<GitCredential["kind"]>(credential?.kind ?? "https_token");
  const [username, setUsername] = useState(credential?.username ?? "oauth2");
  const [secret, setSecret] = useState("");
  const [showSecret, setShowSecret] = useState(false);
  const [checkUrl, setCheckUrl] = useState("");
  const [checking, setChecking] = useState(false);
  const [gitlabApi, setGitlabApi] = useState<GitlabApiState>(() => initialGitlabApi(credential));
  const apiTokenSet = credential?.gitlab_api_token_set ?? false;
  const save = useSaveGitCredential(credential?.id);
  return <>
    <div className="flex flex-col gap-3">
      <div><Label htmlFor="git-access-name">Название</Label>
        <Input id="git-access-name" value={name} onChange={(e) => setName(e.target.value)} /></div>
      <div><Label htmlFor="git-access-kind">Тип доступа</Label>
        <Select value={kind} onValueChange={(v) => setKind(v as GitCredential["kind"])}>
          <SelectTrigger id="git-access-kind"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="https_token">HTTPS-токен</SelectItem>
            <SelectItem value="ssh_key">SSH-ключ</SelectItem></SelectContent>
        </Select></div>
      <div><Label htmlFor="git-access-host">Git-хост</Label>
        <Input id="git-access-host" placeholder="gitlab.example.com" value={host} onChange={(e) => setHost(e.target.value)} /></div>
      {kind === "https_token" && <div><Label htmlFor="git-access-user">Логин HTTPS</Label>
        <Input id="git-access-user" value={username} onChange={(e) => setUsername(e.target.value)} />
        <p className="text-small text-text-3">Для персонального токена GitLab: oauth2.</p></div>}
      <div><Label htmlFor="git-access-secret">{kind === "ssh_key" ? "Приватный SSH-ключ без пароля" : "Токен"}</Label>
        <div className="relative">
        {kind === "ssh_key" && showSecret ?
          <textarea id="git-access-secret" className="w-full rounded-md border border-border bg-surface p-2 pr-12 font-mono text-small"
            rows={6} value={secret} autoComplete="off" spellCheck={false}
            placeholder={credential ? "Оставьте пустым, чтобы сохранить прежний ключ" : ""}
            onChange={(e) => setSecret(e.target.value)} /> :
          <Input id="git-access-secret" className="pr-12" type={showSecret ? "text" : "password"} value={secret}
            autoComplete="new-password" placeholder={credential ? "Оставьте пустым, чтобы сохранить прежний секрет" : ""}
            onPaste={kind === "ssh_key" ? (e) => {
              e.preventDefault();
              setSecret(e.clipboardData.getData("text"));
            } : undefined}
            onChange={(e) => setSecret(e.target.value)} />}
        <Button type="button" variant="ghost" size="icon"
          className="absolute right-0 top-0"
          onClick={() => setShowSecret(!showSecret)}
          aria-label={showSecret ? "Скрыть секрет" : "Показать секрет"}
          title={showSecret ? "Скрыть секрет" : "Показать секрет"}
          aria-controls="git-access-secret" aria-pressed={showSecret}>
          {showSecret ? <EyeOff aria-hidden="true" /> : <Eye aria-hidden="true" />}
        </Button>
        </div>
        <p className="text-small text-text-3">Секрет хранится зашифрованным и не отображается после сохранения.</p></div>
      <GitlabApiFields kind={kind} host={host} tokenSet={apiTokenSet} value={gitlabApi}
        onChange={(patch) => setGitlabApi((prev) => ({ ...prev, ...patch }))} />
    </div>
    {credential && <div className="my-3 flex flex-col gap-2">
      <Label htmlFor="git-access-check">URL для проверки чтения</Label>
      <Input id="git-access-check" value={checkUrl} onChange={(e) => setCheckUrl(e.target.value)} />
      <Button variant="secondary" disabled={!checkUrl || checking} onClick={async () => {
        setChecking(true);
        try {
          const result = await api.post<GitCredentialCheck>(`/git-credentials/${credential.id}/check`, { git_url: checkUrl });
          const apiMessage = gitlabApiCheckMessage(result.gitlab_api);
          const gitMessage = "Чтение доступно. Право записи этой проверкой не проверяется.";
          const message = apiMessage ? `${gitMessage} ${apiMessage}` : gitMessage;
          // Git читается, но API отклонён — ошибка настройки опроса статуса MR.
          if (apiMessage && result.gitlab_api !== GITLAB_API_OK) toast.error(message);
          else toast.success(message);
        } catch (e) { toast.error(errorMessage(e, "Не удалось проверить доступ")); }
        finally { setChecking(false); }
      }}>Проверить сохранённый доступ</Button>
    </div>}
    <DialogFooter><Button variant="secondary" onClick={onSaved}>Отмена</Button>
      <Button disabled={!name.trim() || !host.trim() || !username || (!credential && !secret)
        || gitlabApiTokenMissing(kind, gitlabApi, apiTokenSet) || save.isPending}
        onClick={() => save.mutate({
          name, host, kind, username, ...(secret ? { secret } : {}),
          ...gitlabApiBody(kind, gitlabApi, apiTokenSet),
        }, {
          onSuccess: onSaved, onError: (e) => toast.error(errorMessage(e, "Не удалось сохранить доступ Git")),
        })}>Сохранить</Button></DialogFooter>
  </>;
}

export function GitCredentialsPanel() {
  const { data, isLoading } = useGitCredentials();
  const remove = useDeleteGitCredential();
  const [target, setTarget] = useState<EditTarget<GitCredential>>(null);
  return <div className="flex flex-col gap-3">
    <div className="flex items-center justify-between"><SectionTitle>Учётные данные Git</SectionTitle>
      <Button onClick={() => setTarget("new")}>Добавить</Button></div>
    <p className="text-small text-text-3">Общий доступ для репозиториев Tracker. Выберите сохранённую запись в настройках репозитория.</p>
    {isLoading && <LoadingState />}
    {!isLoading && !data?.length && <p>Учётных данных пока нет.</p>}
    {data?.map((c) => <Card key={c.id} className="flex items-center gap-3">
      <div className="min-w-0 flex-1"><div className="font-bold">{c.name}</div>
        <div className="text-small text-text-3">{c.kind === "ssh_key" ? "SSH" : "HTTPS"} · {c.host}{c.gitlab_api_enabled && " · статус MR"}</div></div>
      <EditButton name={c.name} onClick={() => setTarget(c)} />
      <ConfirmDeleteButton kind="Учётные данные Git" name={c.name} pending={remove.isPending}
        onConfirm={() => remove.mutate(c.id, { onError: toastError("Не удалось удалить доступ Git") })} />
    </Card>)}
    <EntityFormDialog target={target} onClose={() => setTarget(null)} createTitle="Новый доступ Git" editTitle="Редактировать доступ Git">
      {(item, close) => <CredentialForm credential={item} onSaved={close} />}
    </EntityFormDialog>
  </div>;
}
