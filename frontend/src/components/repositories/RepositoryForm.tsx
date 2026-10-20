import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { DialogFooter } from "@/components/ui/dialog";
import { useCreateRepository, useUpdateRepository } from "@/hooks/useRepositories";
import { ApiError } from "@/lib/apiClient";
import type { Repository } from "@/lib/types";

/** Создание и редактирование репозитория: без `repository` — новый. */
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

  function handleSave() {
    const onError = (error: unknown) =>
      toast.error(error instanceof ApiError ? error.message : "Не удалось сохранить репозиторий");
    if (repository) {
      // Ключ хранится зашифрованным и не отдаётся API: пустое поле — оставить прежний.
      updateRepository.mutate(
        { name, git_url: gitUrl, ...(deployKey ? { deploy_key: deployKey } : {}) },
        { onSuccess: onSaved, onError },
      );
    } else {
      createRepository.mutate(
        { name, git_url: gitUrl, deploy_key: deployKey },
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
