import { EmptyState } from "@/components/common/feedback/EmptyState";
import { QueryState } from "@/components/common/feedback/QueryState";
import { TaskArtifactRow } from "@/components/tasks/TaskArtifactRow";
import { CLEANED_DATA_LABEL } from "@/lib/labels";
import type { Task, TaskArtifact } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";

/**
 * Список артефактов задачи (раздел 14.3, 15.2) с загрузкой, сбоем и пустым
 * состоянием: у архивной задачи с удалёнными файлами — причина, иначе — подсказка
 * ``emptyHint``. ``showEmpty=false`` — пусто ничего не показывать (идёт копирование
 * вложений Jira). ``readOnly`` — без удаления файлов.
 */
export function TaskArtifactList({
  task,
  artifacts,
  isLoading,
  isError = false,
  readOnly = false,
  showEmpty = true,
  emptyHint,
}: {
  task: Task;
  artifacts: TaskArtifact[] | undefined;
  isLoading: boolean;
  isError?: boolean;
  readOnly?: boolean;
  showEmpty?: boolean;
  emptyHint?: string;
}) {
  return (
    <QueryState isLoading={isLoading} isError={isError} errorLabel="Не удалось получить артефакты">
      {artifacts?.length ? (
        <div className="flex flex-col">
          {artifacts.map((artifact) => (
            <TaskArtifactRow
              key={artifact.path}
              taskId={task.id}
              artifact={artifact}
              readOnly={readOnly}
            />
          ))}
        </div>
      ) : showEmpty ? (
        task.artifacts_cleaned_at ? (
          <EmptyState
            compact
            title={CLEANED_DATA_LABEL.artifacts_cleaned_at}
            hint={`Файлы архивной задачи удалены ${formatDateTime(task.artifacts_cleaned_at)} по сроку хранения, который задаёт администратор.`}
          />
        ) : (
          <EmptyState compact title="Файлов нет" hint={emptyHint} />
        )
      ) : null}
    </QueryState>
  );
}
