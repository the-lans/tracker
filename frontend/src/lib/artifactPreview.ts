/** Что умеет показать просмотрщик артефактов (раздел 14.3); остальное — только скачать. */
export type PreviewKind = "image" | "markdown" | "text" | "pdf";

/** Сколько байт текстового файла показывается; остальное — скачать целиком. */
export const TEXT_PREVIEW_MAX_BYTES = 2 * 1024 * 1024;

const IMAGE_MIME: Record<string, string> = {
  png: "image/png",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  gif: "image/gif",
  webp: "image/webp",
  avif: "image/avif",
  bmp: "image/bmp",
  svg: "image/svg+xml",
};

const MARKDOWN_EXTENSIONS = new Set(["md", "markdown"]);

// HTML — тоже текст: исходник показывается как есть, страница не открывается.
const TEXT_EXTENSIONS = new Set([
  "txt",
  "log",
  "csv",
  "tsv",
  "json",
  "yaml",
  "yml",
  "xml",
  "ini",
  "toml",
  "cfg",
  "conf",
  "env",
  "sql",
  "py",
  "js",
  "ts",
  "tsx",
  "jsx",
  "css",
  "html",
  "htm",
  "sh",
  "bash",
  "java",
  "kt",
  "go",
  "rs",
  "c",
  "h",
  "cpp",
  "rb",
  "php",
  "diff",
  "patch",
]);

function extensionOf(path: string): string {
  const name = path.split("/").pop() ?? path;
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(dot + 1).toLowerCase() : "";
}

/** Вид просмотра по расширению файла; `null` — просмотра нет. */
export function previewKindOf(path: string): PreviewKind | null {
  const extension = extensionOf(path);
  if (extension in IMAGE_MIME) return "image";
  if (extension === "pdf") return "pdf";
  if (MARKDOWN_EXTENSIONS.has(extension)) return "markdown";
  if (TEXT_EXTENSIONS.has(extension)) return "text";
  return null;
}

/** Тип содержимого для показа картинки или PDF: по расширению, а не по ответу сервера. */
export function previewMimeOf(path: string): string {
  const extension = extensionOf(path);
  return (
    IMAGE_MIME[extension] ??
    (extension === "pdf" ? "application/pdf" : "text/plain;charset=utf-8")
  );
}
