import type { TaskDuplicateRequest, TaskRepositoryAttach } from "@/lib/types";

/** Поля формы задачи, общие для создания и дублирования (раздел 1.2, 14.2). */
export interface TaskFormValues {
  code: string;
  title: string;
  description: string;
  guideUrl: string;
  llmAccountId: string;
  repositories: TaskRepositoryAttach[];
}

export const EMPTY_TASK_FORM: TaskFormValues = {
  code: "",
  title: "",
  description: "",
  guideUrl: "",
  llmAccountId: "",
  repositories: [],
};

export function toTaskRequest(values: TaskFormValues): TaskDuplicateRequest {
  return {
    code: values.code,
    title: values.title,
    description: values.description,
    guide_url: values.guideUrl || null,
    llm_account_id: values.llmAccountId || null,
    repositories: values.repositories,
  };
}
