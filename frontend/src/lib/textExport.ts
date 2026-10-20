import { toast } from "sonner";

/** Раздел 15.2: копирование полного текста вывода в буфер обмена. */
export function copyText(text: string): void {
  navigator.clipboard
    .writeText(text)
    .then(() => toast.success("Скопировано"))
    .catch(() => toast.error("Не удалось скопировать"));
}

/** Раздел 15.2: скачивание полного текста вывода файлом. */
export function downloadText(text: string, filename: string): void {
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
