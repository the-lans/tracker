/**
 * Загрузка содержимого файла шаблона с диска (раздел 15.1): в шаблон
 * сохраняется копия текста файла, а не ссылка на него.
 */

const BYTES_PER_MB = 1024 * 1024;
export const TEMPLATE_FILE_MAX_MB = 1;
export const TEMPLATE_FILE_MAX_BYTES = TEMPLATE_FILE_MAX_MB * BYTES_PER_MB;

export const TEMPLATE_FILE_TOO_LARGE = `Файл больше ${TEMPLATE_FILE_MAX_MB} МБ`;
export const TEMPLATE_FILE_NOT_TEXT = "Файл не в кодировке UTF-8 — нужен текстовый файл";
export const TEMPLATE_FILE_READ_FAILED = "Не удалось прочитать файл";

// Postgres jsonb не хранит U+0000 — сохранение такого текста упало бы на backend;
// заодно это верный признак двоичного файла.
const NUL_CHAR = "\u0000";

export type TemplateFileReadResult =
  | { ok: true; content: string; name: string; size: number }
  | { ok: false; error: string };

export async function readTemplateFile(file: File): Promise<TemplateFileReadResult> {
  if (file.size > TEMPLATE_FILE_MAX_BYTES) {
    return { ok: false, error: TEMPLATE_FILE_TOO_LARGE };
  }
  let buffer: ArrayBuffer;
  try {
    buffer = await file.arrayBuffer();
  } catch {
    return { ok: false, error: TEMPLATE_FILE_READ_FAILED };
  }
  let content: string;
  try {
    content = new TextDecoder("utf-8", { fatal: true }).decode(buffer);
  } catch {
    return { ok: false, error: TEMPLATE_FILE_NOT_TEXT };
  }
  if (content.includes(NUL_CHAR)) {
    return { ok: false, error: TEMPLATE_FILE_NOT_TEXT };
  }
  return { ok: true, content, name: file.name, size: file.size };
}
