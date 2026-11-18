import { Download, ExternalLink } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ArtifactPreviewBody } from "@/components/tasks/ArtifactPreviewBody";
import { useObjectUrl } from "@/hooks/useBlobPreview";
import { useArtifactFile } from "@/hooks/useTaskArtifacts";
import { downloadArtifact } from "@/lib/artifactDownload";
import { previewMimeOf, type PreviewKind } from "@/lib/artifactPreview";
import { errorMessage } from "@/lib/errors";
import type { TaskArtifact } from "@/lib/types";
import { formatDateTime, formatFileSize } from "@/lib/utils";

/**
 * Окно просмотра файла артефакта поверх страницы (раздел 14.3): картинки, PDF, текст
 * и markdown открываются прямо в браузере, без скачивания; из окна файл можно
 * скачать или открыть в новой вкладке браузера.
 */
export function ArtifactPreviewDialog({
  taskId,
  artifact,
  kind,
  open,
  onOpenChange,
}: {
  taskId: string;
  artifact: TaskArtifact;
  kind: PreviewKind;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const {
    data: blob,
    isLoading,
    isError,
  } = useArtifactFile(taskId, artifact.path, artifact.modified_at, open);
  const tabUrl = useObjectUrl(blob, previewMimeOf(artifact.path));

  function handleDownload() {
    downloadArtifact(taskId, artifact.path).catch((error: unknown) =>
      toast.error(errorMessage(error, "Не удалось скачать файл")),
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-5xl">
        <DialogHeader>
          <DialogTitle className="break-all font-mono text-lead">
            {artifact.path}
          </DialogTitle>
          <DialogDescription className="text-meta text-text-3">
            {formatFileSize(artifact.size)} ·{" "}
            {formatDateTime(artifact.modified_at)}
          </DialogDescription>
        </DialogHeader>
        <ArtifactPreviewBody
          kind={kind}
          path={artifact.path}
          blob={blob}
          isLoading={isLoading}
          isError={isError}
        />
        <DialogFooter>
          <Button variant="secondary" size="sm" onClick={handleDownload}>
            <Download className="size-3.5" /> Скачать
          </Button>
          {tabUrl !== null && (
            <Button asChild variant="secondary" size="sm">
              <a href={tabUrl} target="_blank" rel="noreferrer">
                <ExternalLink className="size-3.5" /> Открыть в новой вкладке
              </a>
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
