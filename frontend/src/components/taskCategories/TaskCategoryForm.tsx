import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { DialogFooter } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { EmptyState } from "@/components/common/feedback/EmptyState";
import { AutoAcceptPlanField } from "@/components/tasks/AutoAcceptPlanField";
import { OccupiesSlotField } from "@/components/tasks/OccupiesSlotField";
import { useNodes } from "@/hooks/useNodes";
import { usePipelines } from "@/hooks/usePipelines";
import { useCreateTaskCategory, useUpdateTaskCategory } from "@/hooks/useTaskCategories";
import { toastError } from "@/lib/errors";
import {
  DEFAULT_QUEUE_PRIORITY,
  MAX_QUEUE_PRIORITY,
  MIN_QUEUE_PRIORITY,
  QUEUE_PRIORITY_HINT,
  QUEUE_PRIORITY_RANGE_HINT,
  parseQueuePriority,
} from "@/lib/queuePriority";
import type { TaskCategory } from "@/lib/types";

/** Значение пункта «Без пайплайна» внутри Select. */
const NO_PIPELINE = "none";
const ARCHIVED_SUFFIX = " (в архиве)";

/**
 * Раздел 15.7: категория и настройки, которые получит её новая задача.
 * Архивные пайплайн и промты выбрать нельзя, но уже выбранные остаются.
 */
export function TaskCategoryForm({
  category,
  onSaved,
  onCancel,
}: {
  category?: TaskCategory;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const { data: pipelines } = usePipelines(true);
  const { data: libraryNodes } = useNodes({ libraryOnly: true, includeArchived: true });
  const createCategory = useCreateTaskCategory();
  const updateCategory = useUpdateTaskCategory(category?.id ?? "");

  const [name, setName] = useState(category?.name ?? "");
  const [pipelineId, setPipelineId] = useState<string | null>(category?.pipeline_id ?? null);
  const [autoAcceptPlan, setAutoAcceptPlan] = useState(category?.auto_accept_plan ?? false);
  const [promptIds, setPromptIds] = useState<string[]>(category?.library_prompt_ids ?? []);
  const [priorityDraft, setPriorityDraft] = useState(
    String(category?.queue_priority ?? DEFAULT_QUEUE_PRIORITY),
  );
  const [occupiesSlot, setOccupiesSlot] = useState(category?.occupies_slot ?? false);

  const priority = parseQueuePriority(priorityDraft);
  const pipelineChoices = (pipelines ?? []).filter(
    (pipeline) => !pipeline.is_archived || pipeline.id === pipelineId,
  );
  const promptChoices = (libraryNodes ?? []).filter(
    (node) => !node.is_archived || promptIds.includes(node.id),
  );
  const isPending = createCategory.isPending || updateCategory.isPending;

  function togglePrompt(nodeId: string, checked: boolean) {
    setPromptIds((prev) => (checked ? [...prev, nodeId] : prev.filter((id) => id !== nodeId)));
  }

  function handleSave() {
    if (priority === null) return;
    const body = {
      name: name.trim(),
      pipeline_id: pipelineId,
      auto_accept_plan: autoAcceptPlan,
      library_prompt_ids: promptIds,
      queue_priority: priority,
      occupies_slot: occupiesSlot,
    };
    const options = { onSuccess: onSaved, onError: toastError("Не удалось сохранить категорию") };
    if (category) updateCategory.mutate(body, options);
    else createCategory.mutate(body, options);
  }

  return (
    <>
      <div className="flex flex-col gap-3">
        <div>
          <Label htmlFor="category-name">Название</Label>
          <Input id="category-name" value={name} onChange={(event) => setName(event.target.value)} />
        </div>

        <div className="text-meta text-text-3">
          Настройки ниже копируются в новую задачу этой категории; дальше задача живёт со своими.
        </div>

        <div>
          <Label htmlFor="category-pipeline">Пайплайн по умолчанию</Label>
          <Select
            value={pipelineId ?? NO_PIPELINE}
            onValueChange={(choice) => setPipelineId(choice === NO_PIPELINE ? null : choice)}
          >
            <SelectTrigger id="category-pipeline">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NO_PIPELINE}>Без пайплайна</SelectItem>
              {pipelineChoices.map((pipeline) => (
                <SelectItem key={pipeline.id} value={pipeline.id}>
                  {pipeline.name}
                  {pipeline.is_archived && ARCHIVED_SUFFIX}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <div className="mt-1 text-meta text-text-3">
            Достаётся и задаче без пайплайна, которой категорию выбрали до запуска.
          </div>
        </div>

        <AutoAcceptPlanField checked={autoAcceptPlan} onCheckedChange={setAutoAcceptPlan} />

        <Card>
          <CardTitle>Системные промты задачи</CardTitle>
          <div className="flex flex-col gap-1.5">
            {promptChoices.map((node) => (
              <label key={node.id} className="flex items-center gap-2 text-body">
                <Checkbox
                  checked={promptIds.includes(node.id)}
                  onCheckedChange={(checked) => togglePrompt(node.id, checked === true)}
                />
                <span className="min-w-0 break-words">
                  {node.name}
                  {node.is_archived && ARCHIVED_SUFFIX}
                </span>
              </label>
            ))}
            {promptChoices.length === 0 && (
              <EmptyState
                compact
                title="Промтов в библиотеке пока нет"
                hint="Добавьте промт в «Библиотеке промтов» — затем отметьте его здесь."
              />
            )}
          </div>
        </Card>

        <div>
          <Label htmlFor="category-priority">Приоритет (очередь)</Label>
          <Input
            id="category-priority"
            type="number"
            inputMode="numeric"
            min={MIN_QUEUE_PRIORITY}
            max={MAX_QUEUE_PRIORITY}
            className="w-36"
            value={priorityDraft}
            aria-invalid={priority === null}
            onChange={(event) => setPriorityDraft(event.target.value)}
          />
          <div className="mt-1 text-meta text-text-3">
            {priority === null ? QUEUE_PRIORITY_RANGE_HINT : QUEUE_PRIORITY_HINT}
          </div>
        </div>

        <OccupiesSlotField
          id="category-occupies-slot"
          checked={occupiesSlot}
          onCheckedChange={setOccupiesSlot}
        />
      </div>
      <DialogFooter>
        <Button variant="secondary" onClick={onCancel}>
          Отмена
        </Button>
        <Button onClick={handleSave} disabled={!name.trim() || priority === null || isPending}>
          {category ? "Сохранить" : "Создать"}
        </Button>
      </DialogFooter>
    </>
  );
}
