import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { JiraImportField } from "@/components/tasks/JiraImportField";
import { ParentTaskFields } from "@/components/tasks/ParentTaskFields";
import { TaskCategorySelect } from "@/components/taskCategories/TaskCategorySelect";
import { Label } from "@/components/ui/label";
import { TaskFormFields } from "@/components/tasks/TaskFormFields";
import { EMPTY_TASK_FORM, toTaskRequest, type TaskFormValues } from "@/components/tasks/taskForm.types";
import { useCreateTask } from "@/hooks/useTasks";
import { useTaskCategories } from "@/hooks/useTaskCategories";
import { useTaskCodeError } from "@/hooks/useTaskCodeError";

export function CreateTaskDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const navigate = useNavigate();
  const createTask = useCreateTask();
  const [values, setValues] = useState<TaskFormValues>(EMPTY_TASK_FORM);
  const [parentTaskId, setParentTaskId] = useState("");
  const [useParentSummary, setUseParentSummary] = useState(false);
  const [jiraIssueKey, setJiraIssueKey] = useState<string | null>(null);
  const [categoryId, setCategoryId] = useState<string | null>(null);
  const { data: categories } = useTaskCategories();
  const { codeError, onFieldsChange, onSaveError } = useTaskCodeError("Не удалось создать задачу");

  function changeFields(patch: Partial<TaskFormValues>) {
    onFieldsChange(patch);
    setValues((prev) => ({ ...prev, ...patch }));
  }

  function reset() {
    setValues(EMPTY_TASK_FORM);
    setParentTaskId("");
    setUseParentSummary(false);
    setJiraIssueKey(null);
    setCategoryId(null);
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    createTask.mutate(
      {
        ...toTaskRequest(values),
        parent_task_id: parentTaskId || null,
        use_parent_summary: useParentSummary,
        jira_issue_key: jiraIssueKey,
        category_id: categoryId,
      },
      {
        onSuccess: (task) => {
          reset();
          onOpenChange(false);
          navigate(`/tasks/${task.id}`);
        },
        onError: onSaveError,
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Новая задача</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <JiraImportField
            onImported={(draft) => {
              setJiraIssueKey(draft.code);
              changeFields({
                code: draft.code,
                title: draft.title,
                description: draft.description,
              });
            }}
          />
          <TaskFormFields value={values} onChange={changeFields} codeError={codeError} />
          <div>
            <Label htmlFor="task-category">Категория</Label>
            <TaskCategorySelect
              id="task-category"
              value={categoryId}
              categories={categories ?? []}
              onChange={setCategoryId}
            />
            <div className="mt-1 text-meta text-text-3">
              Задача получит настройки категории: пайплайн, системные промты, приоритет, слот и
              автопринятие плана.
            </div>
          </div>
          <ParentTaskFields
            parentTaskId={parentTaskId}
            useParentSummary={useParentSummary}
            onChange={(patch) => {
              if (patch.parentTaskId !== undefined) setParentTaskId(patch.parentTaskId);
              if (patch.useParentSummary !== undefined) setUseParentSummary(patch.useParentSummary);
            }}
          />
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={() => onOpenChange(false)}>
              Отмена
            </Button>
            <Button type="submit" disabled={createTask.isPending}>
              Создать
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
