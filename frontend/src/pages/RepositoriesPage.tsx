import { useState } from "react";
import { FolderGit2, Plus } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { RepositoryForm } from "@/components/repositories/RepositoryForm";
import { useDeleteRepository, useRepositories } from "@/hooks/useRepositories";
import { ApiError } from "@/lib/apiClient";
import type { Repository } from "@/lib/types";
import { ConfirmDeleteButton } from "@/components/common/actions/ConfirmDeleteButton";
import { EditButton } from "@/components/common/actions/EditButton";
import { EmptyState } from "@/components/common/feedback/EmptyState";
import { PAGE_BODY, PAGE_ROOT } from "@/styles/classes";
import { LoadingState } from "@/components/common/feedback/LoadingState";

export function RepositoriesPage() {
  const { data: repositories, isLoading } = useRepositories();
  const deleteRepository = useDeleteRepository();
  const [dialogRepository, setDialogRepository] = useState<Repository | "new" | null>(null);

  function handleDelete(id: string) {
    deleteRepository.mutate(id, {
      onError: (error) => {
        toast.error(error instanceof ApiError ? error.message : "Не удалось удалить репозиторий");
      },
    });
  }

  return (
    <div className={PAGE_ROOT}>
      <PageHeader
        title="Репозитории"
        actions={
          <Button onClick={() => setDialogRepository("new")}>
            <Plus className="size-4" /> Репозиторий
          </Button>
        }
      />
      <div className={PAGE_BODY}>
        {isLoading && <LoadingState />}
        {!isLoading && (repositories ?? []).length === 0 && (
          <EmptyState
            icon={FolderGit2}
            title="Репозиториев пока нет"
            hint="Нажмите «+ Репозиторий» вверху справа и укажите Git-адрес и deploy-ключ. После этого репозиторий можно привязать к задаче при её создании."
          />
        )}
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {(repositories ?? []).map((repository) => (
            <Card key={repository.id} className="flex flex-col gap-1.5">
              <div className="flex items-center gap-1">
                <div className="min-w-0 flex-1 truncate font-bold" title={repository.name}>
                  {repository.name}
                </div>
                <EditButton name={repository.name} onClick={() => setDialogRepository(repository)} />
                <ConfirmDeleteButton
                  kind="репозиторий"
                  name={repository.name}
                  pending={deleteRepository.isPending}
                  onConfirm={() => handleDelete(repository.id)}
                />
              </div>
              <div className="truncate font-mono text-small text-text-3" title={repository.git_url}>{repository.git_url}</div>
            </Card>
          ))}
        </div>
      </div>

      <Dialog
        open={dialogRepository !== null}
        onOpenChange={(open) => !open && setDialogRepository(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {dialogRepository === "new" ? "Новый репозиторий" : "Редактировать репозиторий"}
            </DialogTitle>
          </DialogHeader>
          {dialogRepository !== null && (
            <RepositoryForm
              repository={dialogRepository === "new" ? undefined : dialogRepository}
              onSaved={() => setDialogRepository(null)}
              onCancel={() => setDialogRepository(null)}
            />
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
