import { ErrorState } from "@/components/common/feedback/ErrorState";
import { LoadingState } from "@/components/common/feedback/LoadingState";
import { AgentMessageText } from "@/components/tasks/AgentMessageText";
import { useBlobText, useObjectUrl } from "@/hooks/useBlobPreview";
import {
  TEXT_PREVIEW_MAX_BYTES,
  previewMimeOf,
  type PreviewKind,
} from "@/lib/artifactPreview";
import { formatFileSize } from "@/lib/utils";

function TextPreview({ blob, markdown }: { blob: Blob; markdown: boolean }) {
  const content = useBlobText(blob, TEXT_PREVIEW_MAX_BYTES);
  if (content === null) return <LoadingState />;
  if (content.binary)
    return (
      <ErrorState label="Файл не текстовый — просмотр недоступен, скачайте его." />
    );
  return (
    <>
      {content.truncated && (
        <p className="mb-2 text-note text-text-3">
          Показаны первые {formatFileSize(TEXT_PREVIEW_MAX_BYTES)} — остальное в
          скачанном файле.
        </p>
      )}
      {markdown ? (
        <AgentMessageText text={content.text} />
      ) : (
        <pre className="whitespace-pre-wrap font-mono text-small leading-relaxed [overflow-wrap:anywhere]">
          {content.text}
        </pre>
      )}
    </>
  );
}

function MediaPreview({
  blob,
  path,
  kind,
}: {
  blob: Blob;
  path: string;
  kind: "image" | "pdf";
}) {
  const url = useObjectUrl(blob, previewMimeOf(path));
  if (url === null) return <LoadingState />;
  return kind === "image" ? (
    <img
      src={url}
      alt={path}
      className="mx-auto max-h-[70vh] max-w-full object-contain"
    />
  ) : (
    <iframe
      src={url}
      title={path}
      className="h-[70vh] w-full rounded-md border border-border"
    />
  );
}

/** Содержимое просмотрщика по виду файла: картинка, PDF, текст или markdown (раздел 14.3). */
export function ArtifactPreviewBody({
  kind,
  path,
  blob,
  isLoading,
  isError,
}: {
  kind: PreviewKind;
  path: string;
  blob: Blob | undefined;
  isLoading: boolean;
  isError: boolean;
}) {
  if (isLoading) return <LoadingState />;
  if (isError || blob === undefined)
    return <ErrorState label="Не удалось открыть файл" />;
  if (kind === "image" || kind === "pdf")
    return <MediaPreview blob={blob} path={path} kind={kind} />;
  return <TextPreview blob={blob} markdown={kind === "markdown"} />;
}
