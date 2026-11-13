import { useState } from "react";
import { Plus, Tags } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ConfirmDeleteButton } from "@/components/common/actions/ConfirmDeleteButton";
import { EditButton } from "@/components/common/actions/EditButton";
import { EntityFormDialog, type EditTarget } from "@/components/common/dialogs/EntityFormDialog";
import { EmptyState } from "@/components/common/feedback/EmptyState";
import { LoadingState } from "@/components/common/feedback/LoadingState";
import { TaskCategoryForm } from "@/components/taskCategories/TaskCategoryForm";
import { usePipelines } from "@/hooks/usePipelines";
import { useDeleteTaskCategory, useTaskCategories } from "@/hooks/useTaskCategories";
import { toastError } from "@/lib/errors";
import type { Pipeline, TaskCategory } from "@/lib/types";
import { plural } from "@/lib/utils";
import { PAGE_BODY, PAGE_ROOT } from "@/styles/classes";

function categorySummary(category: TaskCategory, pipelines: readonly Pipeline[]): string[] {
  const pipeline = pipelines.find((item) => item.id === category.pipeline_id);
  const promptCount = category.library_prompt_ids.length;
  return [
    pipeline ? `Пайплайн: ${pipeline.name}${pipeline.is_archived ? " (в архиве)" : ""}` : "Без пайплайна",
    `Приоритет ${category.queue_priority}`,
    ...(promptCount > 0
      ? [`${promptCount} ${plural(promptCount, ["системный промт", "системных промта", "системных промтов"])}`]
      : []),
    ...(category.auto_accept_plan ? ["План принимается автоматически"] : []),
    ...(category.occupies_slot ? ["Занимает слот"] : []),
  ];
}

/** Раздел 15.7: свои категории задач и настройки их новых задач. */
export function TaskCategoriesPage() {
  const { data: categories, isLoading } = useTaskCategories();
  const { data: pipelines } = usePipelines(true);
  const deleteCategory = useDeleteTaskCategory();
  const [dialogCategory, setDialogCategory] = useState<EditTarget<TaskCategory>>(null);

  return (
    <div className={PAGE_ROOT}>
      <PageHeader
        title="Категории"
        actions={
          <Button onClick={() => setDialogCategory("new")}>
            <Plus className="size-4" /> Категория
          </Button>
        }
      />
      <div className={PAGE_BODY}>
        {isLoading && <LoadingState />}
        {!isLoading && (categories ?? []).length === 0 && (
          <EmptyState
            icon={Tags}
            title="Категорий пока нет"
            hint="Категория группирует задачи на дашборде и задаёт настройки новой задачи: пайплайн, системные промты, приоритет и слот. Нажмите «+ Категория» вверху справа."
          />
        )}
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {(categories ?? []).map((category) => (
            <Card key={category.id} className="flex flex-col gap-1.5">
              <div className="flex items-center gap-1">
                <div className="min-w-0 flex-1 truncate font-bold" title={category.name}>
                  {category.name}
                </div>
                <EditButton name={category.name} onClick={() => setDialogCategory(category)} />
                <ConfirmDeleteButton
                  kind="категорию"
                  name={category.name}
                  pending={deleteCategory.isPending}
                  onConfirm={() =>
                    deleteCategory.mutate(category.id, {
                      onError: toastError("Не удалось удалить"),
                    })}
                />
              </div>
              <ul className="flex flex-col gap-0.5 text-small text-text-3">
                {categorySummary(category, pipelines ?? []).map((line) => (
                  <li key={line} className="break-words">
                    {line}
                  </li>
                ))}
              </ul>
            </Card>
          ))}
        </div>
      </div>

      <EntityFormDialog
        target={dialogCategory}
        onClose={() => setDialogCategory(null)}
        createTitle="Новая категория"
        editTitle="Редактировать категорию"
        contentClassName="max-w-xl"
      >
        {(item, close) => <TaskCategoryForm category={item} onSaved={close} onCancel={close} />}
      </EntityFormDialog>
    </div>
  );
}
