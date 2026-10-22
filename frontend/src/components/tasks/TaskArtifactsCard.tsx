import { useRef, type ChangeEvent } from "react";
import { Upload } from "lucide-react";
import { toast } from "sonner";
import { Card, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/common/feedback/EmptyState";
import { TaskArtifactRow } from "@/components/tasks/TaskArtifactRow";
import { useTaskArtifacts, useUploadTaskArtifact } from "@/hooks/useTaskArtifacts";
import { ApiError } from "@/lib/apiClient";
import type { Task } from "@/lib/types";

/**
 * Раздел 14.3, 15.2: артефакты задачи — файлы для агента и результаты его
 * работы. Доступны в любом статусе задачи и не удаляются очисткой
 * репозиториев; те же файлы видны по SFTP в `<код>/artifacts`.
 */
export function TaskArtifactsCard({ task }: { task: Task }) {
  const { data: artifacts } = useTaskArtifacts(task.id);
  const upload = useUploadTaskArtifact(task.id);
  const inputRef = useRef<HTMLInputElement>(null);

  function handleFiles(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    for (const file of files) {
      upload.mutate(file, {
        onError: (error) =>
          toast.error(
            error instanceof ApiError ? error.message : `Не удалось загрузить ${file.name}`,
          ),
      });
    }
  }

  return (
    <Card>
      <CardTitle>
        <span>Артефакты</span>
        <Button
          size="sm"
          variant="secondary"
          disabled={upload.isPending}
          onClick={() => inputRef.current?.click()}
        >
          <Upload className="size-3.5" /> Загрузить
        </Button>
      </CardTitle>
      <input
        ref={inputRef}
        type="file"
        multiple
        className="hidden"
        aria-label="Файлы артефактов"
        onChange={handleFiles}
      />
      {artifacts?.length ? (
        <div className="flex flex-col">
          {artifacts.map((artifact) => (
            <TaskArtifactRow key={artifact.path} taskId={task.id} artifact={artifact} />
          ))}
        </div>
      ) : (
        <EmptyState
          compact
          title="Файлов нет"
          hint={`Загрузите файлы для агента — в промтах их каталог подставляется как {{task.artifacts_path}}. Агент сохраняет туда результаты; по SFTP каталог виден как ${task.code}/artifacts.`}
        />
      )}
    </Card>
  );
}
