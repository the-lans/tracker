import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useCreateRepository, useUpdateRepository } from "@/hooks/useRepositories";
import { useTemplates } from "@/hooks/useTemplates";
import { ApiError } from "@/lib/apiClient";
import type { Repository } from "@/lib/types";

// Radix Select не принимает пустую строку как значение пункта.
const NO_TEMPLATE = "none";

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
  const [deployKey, setDeployKey] = useState("");
  const [templateId, setTemplateId] = useState(repository?.default_template_id ?? NO_TEMPLATE);
  const { data: templates } = useTemplates();
  const currentTemplateId = repository?.default_template_id ?? null;
  const currentIsForeign =
    currentTemplateId !== null &&
    templates !== undefined &&
    !templates.some((template) => template.id === currentTemplateId);

  function handleSave() {
    const onError = (error: unknown) =>
      toast.error(error instanceof ApiError ? error.message : "Не удалось сохранить репозиторий");
    const defaultTemplateId = templateId === NO_TEMPLATE ? null : templateId;
    if (repository) {
      // Ключ хранится зашифрованным и не отдаётся API: пустое поле — оставить прежний.
      updateRepository.mutate(
        {
          name,
          git_url: gitUrl,
          default_template_id: defaultTemplateId,
          ...(deployKey ? { deploy_key: deployKey } : {}),
        },
        { onSuccess: onSaved, onError },
      );
    } else {
      createRepository.mutate(
        { name, git_url: gitUrl, deploy_key: deployKey, default_template_id: defaultTemplateId },
        { onSuccess: onSaved, onError },
      );
    }
  }

  const isPending = createRepository.isPending || updateRepository.isPending;

  return (
    <>
      <div className="flex flex-col gap-3">
        <div>
          <Label htmlFor="repo-name">Название</Label>
          <Input id="repo-name" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div>
          <Label htmlFor="repo-url">Git URL</Label>
          <Input
            id="repo-url"
            placeholder="git@gitlab.example.com:group/project.git"
            value={gitUrl}
            onChange={(e) => setGitUrl(e.target.value)}
          />
        </div>
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
          <Label htmlFor="repo-key">
            {repository
              ? "Новый deploy-ключ (оставьте пустым, чтобы не менять)"
              : "Deploy-ключ (приватный, SSH)"}
          </Label>
          <Input
            id="repo-key"
            type="password"
            value={deployKey}
            onChange={(e) => setDeployKey(e.target.value)}
          />
        </div>
      </div>
      <DialogFooter>
        <Button variant="secondary" onClick={onCancel}>
          Отмена
        </Button>
        <Button
          onClick={handleSave}
          disabled={!name || !gitUrl || (!repository && !deployKey) || isPending}
        >
          {repository ? "Сохранить" : "Создать"}
        </Button>
      </DialogFooter>
    </>
  );
}
