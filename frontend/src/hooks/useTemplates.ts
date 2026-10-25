import { useMutation, useQuery } from "@tanstack/react-query";
import { useInvalidatingMutation } from "@/hooks/useInvalidatingMutation";
import { api } from "@/lib/apiClient";
import type {
  Template,
  TemplateCreateRequest,
  TemplatePreviewRequest,
  TemplatePreviewResponse,
  TemplateUpdateRequest,
} from "@/lib/types";

const KEY = ["templates"] as const;

export function useTemplates() {
  return useQuery({ queryKey: KEY, queryFn: () => api.get<Template[]>("/templates") });
}

export function useCreateTemplate() {
  return useInvalidatingMutation(
    (body: TemplateCreateRequest) => api.post<Template>("/templates", body),
    [KEY],
  );
}

export function useUpdateTemplate(templateId: string) {
  return useInvalidatingMutation(
    (body: TemplateUpdateRequest) => api.patch<Template>(`/templates/${templateId}`, body),
    [KEY],
  );
}

export function useDeleteTemplate() {
  return useInvalidatingMutation(
    (templateId: string) => api.delete(`/templates/${templateId}`),
    [KEY],
  );
}

/** Раздел 5.1: предпросмотр рендеринга — общий эндпоинт для конструктора
 * пайплайна, библиотеки и свободного ввода. */
export function useTemplatePreview() {
  return useMutation({
    mutationFn: (body: TemplatePreviewRequest) =>
      api.post<TemplatePreviewResponse>("/templates/preview", body),
  });
}
