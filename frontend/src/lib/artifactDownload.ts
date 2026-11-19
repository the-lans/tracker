import { artifactUrl } from "@/hooks/useTaskArtifacts";
import { api } from "@/lib/apiClient";
import { downloadBlob } from "@/lib/textExport";

/** Имя файла артефакта без каталога. */
export function artifactFileName(path: string): string {
  return path.split("/").pop() ?? path;
}

/** Содержимое артефакта с токеном пользователя (раздел 14.3). */
export function fetchArtifact(taskId: string, path: string): Promise<Blob> {
  return api.getBlob(artifactUrl(taskId, path));
}

/** Скачивает артефакт файлом; сбой — исключение для вызывающего кода. */
export async function downloadArtifact(
  taskId: string,
  path: string,
): Promise<void> {
  downloadBlob(await fetchArtifact(taskId, path), artifactFileName(path));
}
