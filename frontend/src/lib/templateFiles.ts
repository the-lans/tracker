/**
 * Загрузка содержимого файла шаблона с диска (раздел 15.1): в шаблон
 * сохраняется копия текста файла, а не ссылка на него.
 */

import type { TemplateFileReadResult } from "@/lib/templateFiles.types";

const BYTES_PER_MB = 1024 * 1024;
export const TEMPLATE_FILE_MAX_MB = 1;
export const TEMPLATE_FILE_MAX_BYTES = TEMPLATE_FILE_MAX_MB * BYTES_PER_MB;

export const TEMPLATE_FILE_TOO_LARGE = `Файл больше ${TEMPLATE_FILE_MAX_MB} МБ`;
export const TEMPLATE_FILE_NOT_TEXT = "Файл не в кодировке UTF-8 — нужен текстовый файл";
export const TEMPLATE_FILE_READ_FAILED = "Не удалось прочитать файл";

// Postgres jsonb не хранит U+0000 — сохранение такого текста упало бы на backend;
// заодно это верный признак двоичного файла.
const NUL_CHAR = "\u0000";

export function duplicatePathMessage(path: string): string {
  return `Путь ${path} уже есть в шаблоне`;
}

/**
 * Пути, которые встречаются в шаблоне больше одного раза (без пробелов по
 * краям, пустые не считаются): файлы шаблона — словарь по пути, при
 * сохранении второй такой файл молча заменил бы первый.
 */
export function duplicateTemplatePaths(paths: string[]): Set<string> {
  const seen = new Set<string>();
  const duplicates = new Set<string>();
  for (const path of paths.map((value) => value.trim()).filter(Boolean)) {
    if (seen.has(path)) duplicates.add(path);
    seen.add(path);
  }
  return duplicates;
}

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
