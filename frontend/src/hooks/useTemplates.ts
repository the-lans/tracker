import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: TemplateCreateRequest) => api.post<Template>("/templates", body),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: KEY }),
  });
}

export function useUpdateTemplate(templateId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: TemplateUpdateRequest) =>
      api.patch<Template>(`/templates/${templateId}`, body),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: KEY }),
  });
}

export function useDeleteTemplate() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (templateId: string) => api.delete(`/templates/${templateId}`),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: KEY }),
  });
}

/** Раздел 5.1: предпросмотр рендеринга — общий эндпоинт для конструктора
 * пайплайна, библиотеки и свободного ввода. */
export function useTemplatePreview() {
  return useMutation({
    mutationFn: (body: TemplatePreviewRequest) =>
      api.post<TemplatePreviewResponse>("/templates/preview", body),
  });
}
