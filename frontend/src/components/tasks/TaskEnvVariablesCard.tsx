import { useState, type FormEvent } from "react";
import { Plus } from "lucide-react";
import { toast } from "sonner";
import { Card, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { TaskEnvVariableRow } from "@/components/tasks/TaskEnvVariableRow";
import { useCreateTaskEnvVariable, useTaskEnvVariables } from "@/hooks/useTaskEnvVariables";
import { ApiError } from "@/lib/apiClient";
import { TaskStatus, type Task } from "@/lib/types";

/** Раздел 5, 15.2: переменные уровня задачи — приоритет над репозиторием и
 * глобальными; подставляются в момент отправки, поэтому меняются и во время
 * выполнения (кроме выполненной задачи). */
export function TaskEnvVariablesCard({ task }: { task: Task }) {
  const { data: variables } = useTaskEnvVariables(task.id);
  const create = useCreateTaskEnvVariable(task.id);
  const [key, setKey] = useState("");
  const [value, setValue] = useState("");
  const readOnly = task.status === TaskStatus.DONE;

  function handleAdd(event: FormEvent) {
    event.preventDefault();
    create.mutate(
      { key: key.trim(), value },
      {
        onSuccess: () => {
          setKey("");
          setValue("");
        },
        onError: (error) =>
          toast.error(error instanceof ApiError ? error.message : "Не удалось добавить переменную"),
      },
    );
  }

  return (
    <Card>
      <CardTitle>
        <span>Переменные задачи</span>
        {variables && <span>{variables.length}</span>}
      </CardTitle>
      {variables?.length ? (
        <div className="flex flex-col">
          {variables.map((variable) => (
            <TaskEnvVariableRow
              key={variable.id}
              taskId={task.id}
              variable={variable}
              readOnly={readOnly}
            />
          ))}
        </div>
      ) : (
        <div className="text-[12.5px] text-text-3">
          Не заданы — {"{{env.*}}"} берётся из репозиториев и глобальных переменных
        </div>
      )}
      {!readOnly && (
        <form onSubmit={handleAdd} className="mt-2 flex flex-col gap-2">
          <div className="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] gap-2">
            <Input
              aria-label="Ключ переменной"
              placeholder="API_URL"
              className="font-mono"
              value={key}
              onChange={(event) => setKey(event.target.value)}
              required
            />
            <Input
              aria-label="Значение переменной"
              placeholder="Значение"
              value={value}
              onChange={(event) => setValue(event.target.value)}
              required
            />
          </div>
          <Button
            type="submit"
            size="sm"
            variant="secondary"
            className="self-end"
            disabled={create.isPending}
          >
            <Plus className="size-4" /> Добавить
          </Button>
        </form>
      )}
    </Card>
  );
}
