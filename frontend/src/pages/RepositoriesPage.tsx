import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useCreateRepository, useDeleteRepository, useRepositories } from "@/hooks/useRepositories";
import { ApiError } from "@/lib/apiClient";

export function RepositoriesPage() {
  const { data: repositories, isLoading } = useRepositories();
  const createRepository = useCreateRepository();
  const deleteRepository = useDeleteRepository();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [gitUrl, setGitUrl] = useState("");
  const [deployKey, setDeployKey] = useState("");

  function handleCreate() {
    createRepository.mutate(
      { name, git_url: gitUrl, deploy_key: deployKey },
      {
        onSuccess: () => {
          setOpen(false);
          setName("");
          setGitUrl("");
          setDeployKey("");
        },
        onError: (error) => {
          toast.error(error instanceof ApiError ? error.message : "Не удалось создать репозиторий");
        },
      },
    );
  }

  function handleDelete(id: string) {
    deleteRepository.mutate(id, {
      onError: (error) => {
        toast.error(error instanceof ApiError ? error.message : "Не удалось удалить репозиторий");
      },
    });
  }

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Репозитории"
        actions={
          <Button onClick={() => setOpen(true)}>
            <Plus className="size-4" /> Репозиторий
          </Button>
        }
      />
      <div className="min-h-0 flex-1 overflow-auto px-5 pb-8 lg:px-8">
        {isLoading && <div className="text-text-3">Загрузка…</div>}
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {(repositories ?? []).map((repository) => (
            <Card key={repository.id} className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between">
                <div className="font-bold">{repository.name}</div>
                <button
                  type="button"
                  onClick={() => handleDelete(repository.id)}
                  className="touch-target flex items-center justify-center text-text-3 hover:text-danger"
                  aria-label="Удалить"
                >
                  <Trash2 className="size-4" />
                </button>
              </div>
              <div className="truncate font-mono text-[12px] text-text-3">{repository.git_url}</div>
            </Card>
          ))}
        </div>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Новый репозиторий</DialogTitle>
          </DialogHeader>
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
              <Label htmlFor="repo-key">Deploy-ключ (приватный, SSH)</Label>
              <Input
                id="repo-key"
                type="password"
                value={deployKey}
                onChange={(e) => setDeployKey(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setOpen(false)}>
              Отмена
            </Button>
            <Button
              onClick={handleCreate}
              disabled={!name || !gitUrl || !deployKey || createRepository.isPending}
            >
              Создать
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
