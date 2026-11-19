import { useEffect, useState } from "react";

/**
 * Временный адрес файла для `<img>`, `<iframe>` и новой вкладки; освобождается при
 * смене файла и размонтировании. Пока адрес не создан (или файла нет) — `null`.
 */
export function useObjectUrl(
  blob: Blob | undefined,
  type?: string,
): string | null {
  const [entry, setEntry] = useState<{
    blob: Blob;
    type?: string;
    url: string;
  } | null>(null);
  useEffect(() => {
    if (blob === undefined) return;
    const url = URL.createObjectURL(type ? new Blob([blob], { type }) : blob);
    // Адрес создаёт внешний ресурс браузера (URL API): эффект синхронизирует его с состоянием.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setEntry({ blob, type, url });
    return () => URL.revokeObjectURL(url);
  }, [blob, type]);
  return blob !== undefined && entry?.blob === blob && entry.type === type
    ? entry.url
    : null;
}

export interface BlobText {
  text: string;
  /** Файл длиннее предела — показано только начало. */
  truncated: boolean;
  /** В начале файла нули: это не текст. */
  binary: boolean;
}

function readText(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(blob);
  });
}

/** Начало файла (до ``maxBytes``) как текст; `null`, пока читается. */
export function useBlobText(
  blob: Blob | undefined,
  maxBytes: number,
): BlobText | null {
  const [entry, setEntry] = useState<{ blob: Blob; value: BlobText } | null>(
    null,
  );
  useEffect(() => {
    if (blob === undefined) return;
    let active = true;
    readText(blob.slice(0, maxBytes))
      .then((text) => ({
        text,
        truncated: blob.size > maxBytes,
        binary: text.includes("\u0000"),
      }))
      .catch((): BlobText => ({ text: "", truncated: false, binary: true }))
      .then((value) => {
        if (active) setEntry({ blob, value });
      });
    return () => {
      active = false;
    };
  }, [blob, maxBytes]);
  return blob !== undefined && entry?.blob === blob ? entry.value : null;
}
