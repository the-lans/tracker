import { Download, FileText } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { ConfirmDeleteButton } from "@/components/common/actions/ConfirmDeleteButton";
import { artifactUrl, useDeleteTaskArtifact } from "@/hooks/useTaskArtifacts";
import { api } from "@/lib/apiClient";
import { errorMessage, toastError } from "@/lib/errors";
import { downloadBlob } from "@/lib/textExport";
import { formatDateTime, formatFileSize } from "@/lib/utils";
import type { TaskArtifact } from "@/lib/types";

function fileName(path: string): string {
  return path.split("/").pop() ?? path;
}

/** Один файл артефактов: скачать или удалить. */
export function TaskArtifactRow({ taskId, artifact }: { taskId: string; artifact: TaskArtifact }) {
  const remove = useDeleteTaskArtifact(taskId);

  function handleDownload() {
    api
      .getBlob(artifactUrl(taskId, artifact.path))
      .then((blob) => downloadBlob(blob, fileName(artifact.path)))
      .catch((error: unknown) =>
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
      <Button
        size="icon"
        variant="ghost"
        aria-label={`Скачать ${artifact.path}`}
        onClick={handleDownload}
      >
        <Download className="size-4" />
      </Button>
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
    </div>
  );
}
