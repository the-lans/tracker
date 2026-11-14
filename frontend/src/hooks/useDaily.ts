import { useMutation, useQuery } from "@tanstack/react-query";
import { useInvalidatingMutation } from "@/hooks/useInvalidatingMutation";
import { api } from "@/lib/apiClient";
import type {
  DailyCalendar,
  DailyDay,
  DailyEvent,
  DailyEventRequest,
  DailyPlan,
  DailyTemplate,
  TaskDayMarks,
} from "@/lib/daily.types";

export const dailyKeys = {
  all: ["daily"] as const,
  calendar: ["daily", "calendar"] as const,
  marks: ["daily", "marks"] as const,
  day: (day: string) => ["daily", "days", day] as const,
  plans: ["daily", "plans"] as const,
  template: ["daily", "template"] as const,
};

/** Раздел 15.8: сегодня, вчера, завтра и дни «Истории» — по началу дня из настроек. */
export function useDailyCalendar() {
  return useQuery({
    queryKey: dailyKeys.calendar,
    queryFn: () => api.get<DailyCalendar>("/daily/calendar"),
  });
}

/** Отметки вчера, сегодня и завтра по задачам (id задачи → дни): фильтр дашборда и переключатели задачи. */
export function useDayMarks() {
  return useQuery({
    queryKey: dailyKeys.marks,
    queryFn: () => api.get<TaskDayMarks[]>("/daily/marks"),
    select: (marks) => new Map(marks.map((item) => [item.task_id, new Set(item.days)])),
  });
}

export function useDailyDay(day: string | undefined) {
  return useQuery({
    queryKey: dailyKeys.day(day ?? ""),
    queryFn: () => api.get<DailyDay>(`/daily/days/${day}`),
    enabled: Boolean(day),
  });
}

/** Отметка задачи на день; перечитываются отметки и история дней. */
export function useToggleDayMark(taskId: string) {
  return useInvalidatingMutation(
    ({ day, marked }: { day: string; marked: boolean }) =>
      marked ? api.put<void>(`/tasks/${taskId}/day-marks/${day}`) : api.delete(`/tasks/${taskId}/day-marks/${day}`),
    [dailyKeys.all],
  );
}

export function useCreateDailyEvent() {
  return useInvalidatingMutation(
    (body: DailyEventRequest) => api.post<DailyEvent>("/daily/events", body),
    [dailyKeys.all],
  );
}

export function useUpdateDailyEvent(eventId: string) {
  return useInvalidatingMutation(
    (body: DailyEventRequest) => api.put<DailyEvent>(`/daily/events/${eventId}`, body),
    [dailyKeys.all],
  );
}

export function useSetDailyEventHidden(eventId: string) {
  return useInvalidatingMutation(
    (hidden: boolean) => api.put<DailyEvent>(`/daily/events/${eventId}/hidden`, { hidden }),
    [dailyKeys.all],
  );
}

export function useDeleteDailyEvent() {
  return useInvalidatingMutation((eventId: string) => api.delete(`/daily/events/${eventId}`), [dailyKeys.all]);
}

export function useDailyPlans() {
  return useQuery({
    queryKey: dailyKeys.plans,
    queryFn: () => api.get<DailyPlan[]>("/daily/plans"),
  });
}

export function useCreateDailyPlan() {
  return useInvalidatingMutation(
    (day: string) => api.post<DailyPlan>("/daily/plans", { day }),
    [dailyKeys.plans],
  );
}

export function useUpdateDailyPlan(planId: string) {
  return useInvalidatingMutation(
    (content: string) => api.put<DailyPlan>(`/daily/plans/${planId}`, { content }),
    [dailyKeys.plans],
  );
}

export function useRegenerateDailyPlan(planId: string) {
  return useInvalidatingMutation(
    () => api.post<DailyPlan>(`/daily/plans/${planId}/regenerate`),
    [dailyKeys.plans],
  );
}

export function useDeleteDailyPlan() {
  return useInvalidatingMutation((planId: string) => api.delete(`/daily/plans/${planId}`), [dailyKeys.plans]);
}

export function useDailyTemplate() {
  return useQuery({
    queryKey: dailyKeys.template,
    queryFn: () => api.get<DailyTemplate>("/daily/template"),
  });
}

export function useSaveDailyTemplate() {
  return useInvalidatingMutation(
    (content: string) => api.put<DailyTemplate>("/daily/template", { content }),
    [dailyKeys.template],
  );
}

export function useResetDailyTemplate() {
  return useInvalidatingMutation(() => api.delete<DailyTemplate>("/daily/template"), [dailyKeys.template]);
}

/** Шаблон, собранный на сегодня, — без сохранения. */
export function usePreviewDailyTemplate() {
  return useMutation({
    mutationFn: (content: string) => api.post<{ content: string }>("/daily/template/preview", { content }),
  });
}
