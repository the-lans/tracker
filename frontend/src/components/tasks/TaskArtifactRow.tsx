import { useState } from "react";
import { Download, Eye, FileText } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { ConfirmDeleteButton } from "@/components/common/actions/ConfirmDeleteButton";
import { ArtifactPreviewDialog } from "@/components/tasks/ArtifactPreviewDialog";
import { useDeleteTaskArtifact } from "@/hooks/useTaskArtifacts";
import { downloadArtifact } from "@/lib/artifactDownload";
import { previewKindOf } from "@/lib/artifactPreview";
import { errorMessage, toastError } from "@/lib/errors";
import { formatDateTime, formatFileSize } from "@/lib/utils";
import type { TaskArtifact } from "@/lib/types";

/**
 * Один файл артефактов: просмотреть (картинки, текст, markdown, PDF), скачать
 * или удалить.
 */
export function TaskArtifactRow({
  taskId,
  artifact,
  readOnly = false,
}: {
  taskId: string;
  artifact: TaskArtifact;
  /** Без удаления (окно «Описание задачи»). */
  readOnly?: boolean;
}) {
  const remove = useDeleteTaskArtifact(taskId);
  const [previewOpen, setPreviewOpen] = useState(false);
  const previewKind = previewKindOf(artifact.path);

  function handleDownload() {
    downloadArtifact(taskId, artifact.path).catch((error: unknown) =>
      toast.error(errorMessage(error, "Не удалось скачать файл")),
    );
  }

  return (
    <div className="flex min-w-0 items-center gap-2 border-t border-border py-2 first:border-t-0">
      <FileText className="size-4 shrink-0 text-text-3" />
      <div className="min-w-0 flex-1">
        <div className="truncate font-mono text-small font-bold" title={artifact.path}>
          {artifact.path}
        </div>
        <div className="text-meta text-text-3">
          {formatFileSize(artifact.size)} · {formatDateTime(artifact.modified_at)}
        </div>
      </div>
      {previewKind !== null && (
        <>
          <Button
            size="icon"
            variant="ghost"
            aria-label={`Просмотреть ${artifact.path}`}
            onClick={() => setPreviewOpen(true)}
          >
            <Eye className="size-4" />
          </Button>
          {previewOpen && (
            <ArtifactPreviewDialog
              taskId={taskId}
              artifact={artifact}
              kind={previewKind}
              open
              onOpenChange={setPreviewOpen}
            />
          )}
        </>
      )}
      <Button
        size="icon"
        variant="ghost"
        aria-label={`Скачать ${artifact.path}`}
        onClick={handleDownload}
      >
        <Download className="size-4" />
      </Button>
      {!readOnly && (
        <ConfirmDeleteButton
          kind="файл"
          name={artifact.path}
          pending={remove.isPending}
          onConfirm={() =>
            remove.mutate(artifact.path, {
              onError: toastError("Не удалось удалить файл"),
            })
          }
        />
      )}
    </div>
  );
}
