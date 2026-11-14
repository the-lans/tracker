import { useQuery } from "@tanstack/react-query";
import { useInvalidatingMutation } from "@/hooks/useInvalidatingMutation";
import { api } from "@/lib/apiClient";
import type { TaskCategory, TaskCategoryRequest } from "@/lib/types";

const KEY = ["task-categories"] as const;

/**
 * Раздел 15.7: свои категории; `authorId` — категории автора чужой задачи
 * (только у администратора).
 */
export function useTaskCategories(authorId?: string) {
  return useQuery({
    queryKey: [...KEY, authorId ?? "own"],
    queryFn: () => api.get<TaskCategory[]>("/task-categories", { author_id: authorId }),
  });
}

export function useCreateTaskCategory() {
  return useInvalidatingMutation(
    (body: TaskCategoryRequest) => api.post<TaskCategory>("/task-categories", body),
    [KEY],
  );
}

export function useUpdateTaskCategory(categoryId: string) {
  return useInvalidatingMutation(
    (body: TaskCategoryRequest) => api.put<TaskCategory>(`/task-categories/${categoryId}`, body),
    [KEY],
  );
}

/** Задачи удалённой категории остаются без категории — их списки перечитываются. */
export function useDeleteTaskCategory() {
  return useInvalidatingMutation(
    (categoryId: string) => api.delete(`/task-categories/${categoryId}`),
    [KEY, ["tasks"]],
  );
}
