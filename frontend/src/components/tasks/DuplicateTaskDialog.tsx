import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { TaskFormFields } from "@/components/tasks/TaskFormFields";
import { toTaskRequest, type TaskFormValues } from "@/components/tasks/taskForm.types";
import { useDuplicateTask, useTaskRepositories } from "@/hooks/useTasks";
import { ApiError } from "@/lib/apiClient";
import type { Task, TaskRepository } from "@/lib/types";

function initialValues(task: Task, repositories: TaskRepository[]): TaskFormValues {
  return {
    // Код задачи уникален и задаёт рабочую ветку — у копии он новый.
    code: "",
    title: task.title,
    description: task.description,
    guideUrl: task.guide_url ?? "",
    llmAccountId: task.llm_account_id ?? "",
    repositories: repositories.map((attached) => ({
      repository_id: attached.repository_id,
      role: attached.role,
      base_branch: attached.base_branch,
    })),
  };
}

function DuplicateTaskForm({
  task,
  repositories,
  onClose,
}: {
  task: Task;
  repositories: TaskRepository[];
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const duplicateTask = useDuplicateTask(task.id);
  const [values, setValues] = useState(() => initialValues(task, repositories));

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    duplicateTask.mutate(toTaskRequest(values), {
      onSuccess: (copy) => {
        onClose();
        navigate(`/tasks/${copy.id}`);
      },
      onError: (error) => {
        toast.error(error instanceof ApiError ? error.message : "Не удалось дублировать задачу");
      },
    });
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3">
      <TaskFormFields
        value={values}
        onChange={(patch) => setValues((prev) => ({ ...prev, ...patch }))}
      />
      <div className="text-[11.5px] text-text-3">
        В копию перейдут пайплайн с отмеченными нодами, переменные задачи и системные промты.
        История, сессия и родитель не копируются.
      </div>
      <DialogFooter>
        <Button type="button" variant="secondary" onClick={onClose}>
          Отмена
        </Button>
        <Button type="submit" disabled={duplicateTask.isPending}>
          Создать копию
        </Button>
      </DialogFooter>
    </form>
  );
}

/** Раздел 14.2 «Дублировать задачу»: форма создания, заполненная из исходной. */
export function DuplicateTaskDialog({
  task,
  open,
  onOpenChange,
}: {
  task: Task;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { data: repositories } = useTaskRepositories(task.id);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Дублировать {task.code}</DialogTitle>
        </DialogHeader>
        {open && repositories ? (
          <DuplicateTaskForm
            task={task}
            repositories={repositories}
            onClose={() => onOpenChange(false)}
          />
        ) : (
          <div className="text-[12.5px] text-text-3">Загрузка…</div>
        )}
      </DialogContent>
    </Dialog>
  );
}
