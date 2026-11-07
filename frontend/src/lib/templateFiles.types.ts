/** Итог чтения файла шаблона с диска: текст файла или причина отказа для показа под полем. */
export type TemplateFileReadResult =
  | { ok: true; content: string; name: string; size: number }
  | { ok: false; error: string };
