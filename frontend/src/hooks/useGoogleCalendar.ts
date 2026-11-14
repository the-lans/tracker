import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { dailyKeys } from "@/hooks/useDaily";
import { useInvalidatingMutation } from "@/hooks/useInvalidatingMutation";
import { ApiError, api } from "@/lib/apiClient";
import type { GoogleCalendarConnection, GoogleCalendarInfo, GoogleCalendarSyncResult } from "@/lib/daily.types";

const KEY = ["google-calendar"] as const;
const CALENDARS_KEY = ["google-calendar", "calendars"] as const;

/** Раздел 19.8: подключение к Google Calendar; `null` — календарь не подключён. */
export function useGoogleCalendar() {
  return useQuery({
    queryKey: KEY,
    queryFn: () => api.get<GoogleCalendarConnection | null>("/profile/google-calendar"),
  });
}

/**
 * Календари аккаунта. 409 — Google отозвал доступ: подключение уже в статусе
 * «нужен повторный вход», карточка перечитывает его и предлагает войти снова.
 */
export function useGoogleCalendars(enabled: boolean) {
  const queryClient = useQueryClient();
  return useQuery({
    queryKey: CALENDARS_KEY,
    queryFn: async () => {
      try {
        return await api.get<GoogleCalendarInfo[]>("/profile/google-calendar/calendars");
      } catch (error) {
        if (error instanceof ApiError && error.status === 409) {
          void queryClient.invalidateQueries({ queryKey: KEY, exact: true });
        }
        throw error;
      }
    },
    enabled,
  });
}

/** Ссылка входа у Google: браузер уходит на неё и возвращается в профиль. */
export function useStartGoogleCalendarLogin() {
  return useMutation({ mutationFn: () => api.post<{ url: string }>("/profile/google-calendar/login") });
}

export function useSetGoogleCalendars() {
  return useInvalidatingMutation(
    (calendarIds: string[]) =>
      api.put<GoogleCalendarConnection>("/profile/google-calendar/calendars", { calendar_ids: calendarIds }),
    [KEY],
  );
}

export function useSyncGoogleCalendar() {
  return useInvalidatingMutation(
    () => api.post<GoogleCalendarSyncResult>("/profile/google-calendar/sync"),
    [KEY, dailyKeys.all],
  );
}

export function useDisconnectGoogleCalendar() {
  return useInvalidatingMutation(() => api.delete("/profile/google-calendar"), [KEY, dailyKeys.all]);
}
