import { useEffect, useRef } from "react";
import { useTaskArtifacts, artifactUrl } from "@/hooks/useTaskArtifacts";
import { api } from "@/lib/apiClient";
import {
  ARTIFACT_ATTRIBUTE,
  prepareDescriptionHtml,
} from "@/lib/descriptionHtml";

/** Оформление HTML Jira: заголовки, списки, таблицы, код, цитаты (без своих стилей Jira). */
const CONTENT_CLASSES = [
  "isolate overflow-x-auto text-body leading-relaxed text-text-2 break-words",
  "[&_h1]:mt-3 [&_h1]:mb-1 [&_h1]:text-subtitle [&_h1]:font-bold [&_h1]:text",
  "[&_h2]:mt-3 [&_h2]:mb-1 [&_h2]:text-card-title [&_h2]:font-bold [&_h2]:text",
  "[&_h3]:mt-2 [&_h3]:mb-1 [&_h3]:font-bold [&_h3]:text",
  "[&_h4]:mt-2 [&_h4]:mb-1 [&_h4]:font-bold [&_h4]:text",
  "[&_p]:my-2 [&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-5",
  "[&_a]:text-accent [&_a]:underline [&_blockquote]:my-2 [&_blockquote]:border-l-2 [&_blockquote]:border-border [&_blockquote]:pl-3",
  "[&_pre]:my-2 [&_pre]:overflow-x-auto [&_pre]:rounded [&_pre]:bg-surface-2 [&_pre]:p-2",
  "[&_code]:rounded [&_code]:bg-surface-2 [&_code]:px-1 [&_code]:font-mono",
  "[&_table]:my-2 [&_table]:border-collapse [&_th]:border [&_td]:border [&_th]:border-border [&_td]:border-border [&_th]:px-2 [&_td]:px-2",
  "[&_img]:max-w-full",
].join(" ");

interface TaskDescriptionHtmlProps {
  taskId: string;
  html: string;
  jiraUrl: string | null;
}

/**
 * Описание задачи, отрисованное Jira (раздел 15.6). HTML очищается до вставки;
 * картинки — вложения Jira, скопированные в артефакты, подгружаются с токеном
 * пользователя и показываются через временный адрес.
 */
export function TaskDescriptionHtml({
  taskId,
  html,
  jiraUrl,
}: TaskDescriptionHtmlProps) {
  const container = useRef<HTMLDivElement>(null);
  const { data: artifacts } = useTaskArtifacts(taskId, false);
  const artifactNames =
    artifacts?.map((artifact) => artifact.path).join("\n") ?? "";

  useEffect(() => {
    const root = container.current;
    if (root === null) return;
    const names = new Set(
      artifactNames === "" ? [] : artifactNames.split("\n"),
    );
    root.replaceChildren(
      prepareDescriptionHtml(html, { artifacts: names, jiraUrl }),
    );
    const objectUrls: string[] = [];
    let active = true;
    root
      .querySelectorAll<HTMLImageElement>(`img[${ARTIFACT_ATTRIBUTE}]`)
      .forEach((image) => {
        const name = image.getAttribute(ARTIFACT_ATTRIBUTE) ?? "";
        api
          .getBlob(artifactUrl(taskId, name))
          .then((blob) => {
            if (!active) return;
            const url = URL.createObjectURL(blob);
            objectUrls.push(url);
            image.src = url;
          })
          .catch(() => {
            if (active) image.replaceWith(document.createTextNode(`[${name}]`));
          });
      });
    return () => {
      active = false;
      objectUrls.forEach((url) => URL.revokeObjectURL(url));
    };
  }, [html, jiraUrl, taskId, artifactNames]);

  return <div ref={container} className={CONTENT_CLASSES} />;
}
