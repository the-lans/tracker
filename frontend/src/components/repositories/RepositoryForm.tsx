import { useGitCredentials } from "@/hooks/useGitCredentials";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { RepositoryBranchField } from "@/components/repositories/RepositoryBranchField";
import { useCreateRepository, useUpdateRepository } from "@/hooks/useRepositories";
import { useTemplates } from "@/hooks/useTemplates";
import { errorMessage } from "@/lib/errors";
import type { Repository } from "@/lib/types";

// Radix Select не принимает пустую строку как значение пункта.
const NO_TEMPLATE = "none";
const NO_CREDENTIAL = "none";
/** Раздел 3.1: ветка нового репозитория, пока её не задали иначе. */
const DEFAULT_REPOSITORY_BRANCH = "master";

/**
 * Создание и редактирование репозитория: без `repository` — новый.
 * Шаблон по умолчанию выбирается среди доступных пользователю (решение №16
 * плана); уже назначенный чужой шаблон показывается отдельным пунктом и
 * при сохранении не меняется.
 */
export function RepositoryForm({
  repository,
  onSaved,
  onCancel,
}: {
  repository?: Repository;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const createRepository = useCreateRepository();
  const updateRepository = useUpdateRepository(repository?.id ?? "");
  const [name, setName] = useState(repository?.name ?? "");
  const [gitUrl, setGitUrl] = useState(repository?.git_url ?? "");
  const [defaultBranch, setDefaultBranch] = useState(
    repository?.default_branch ?? DEFAULT_REPOSITORY_BRANCH,
  );
  const [credentialId, setCredentialId] = useState(repository?.git_credential_id ?? NO_CREDENTIAL);
  const { data: credentials } = useGitCredentials();
  const [templateId, setTemplateId] = useState(repository?.default_template_id ?? NO_TEMPLATE);
  const { data: templates } = useTemplates();
  const currentTemplateId = repository?.default_template_id ?? null;
  const currentIsForeign =
    currentTemplateId !== null &&
    templates !== undefined &&
    !templates.some((template) => template.id === currentTemplateId);

  function handleSave() {
    const onError = (error: unknown) =>
      toast.error(errorMessage(error, "Не удалось сохранить репозиторий"));
    const body = {
      name,
      git_url: gitUrl,
      default_branch: defaultBranch.trim(),
      default_template_id: templateId === NO_TEMPLATE ? null : templateId,
      git_credential_id: selectedCredentialId,
    };
    if (repository) {
      updateRepository.mutate(body, { onSuccess: onSaved, onError });
    } else {
      createRepository.mutate(body, { onSuccess: onSaved, onError });
    }
  }

  const selectedCredentialId = credentialId === NO_CREDENTIAL ? null : credentialId;
  const isPending = createRepository.isPending || updateRepository.isPending;

  return (
    <>
      <div className="flex flex-col gap-3">
        <div>
          <Label htmlFor="repo-name" required>Название</Label>
          <Input id="repo-name" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div>
          <Label htmlFor="repo-url" required>Git URL</Label>
          <Input
            id="repo-url"
            placeholder="git@gitlab.example.com:group/project.git"
            value={gitUrl}
            onChange={(e) => setGitUrl(e.target.value)}
          />
        </div>
        <RepositoryBranchField
          value={defaultBranch}
          onChange={setDefaultBranch}
          gitUrl={gitUrl}
          credentialId={selectedCredentialId}
        />
        <div>
          <Label htmlFor="repo-template">Шаблон по умолчанию</Label>
          <Select value={templateId} onValueChange={setTemplateId}>
            <SelectTrigger id="repo-template">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NO_TEMPLATE}>Без шаблона</SelectItem>
              {currentIsForeign && (
                <SelectItem value={currentTemplateId}>Шаблон другого пользователя</SelectItem>
              )}
              {(templates ?? []).map((template) => (
                <SelectItem key={template.id} value={template.id}>
                  {template.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div>
          <Label htmlFor="repo-credential">Учётные данные Git</Label>
          <Select value={credentialId} onValueChange={setCredentialId}>
            <SelectTrigger id="repo-credential"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value={NO_CREDENTIAL}>Без авторизации (публичный HTTPS)</SelectItem>
              {(credentials ?? []).map((c) => <SelectItem key={c.id} value={c.id}>{c.name} · {c.host}</SelectItem>)}
            </SelectContent>
          </Select>
          <p className="text-small text-text-3">Доступы добавляются в администрировании → «Учётные данные Git».</p>
        </div>
      </div>
      <DialogFooter>
        <Button variant="secondary" onClick={onCancel}>
          Отмена
        </Button>
        <Button
          onClick={handleSave}
          disabled={!name || !gitUrl || !defaultBranch.trim() || isPending}
        >
          {repository ? "Сохранить" : "Создать"}
        </Button>
      </DialogFooter>
    </>
  );
}
