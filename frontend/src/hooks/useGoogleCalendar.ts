import { useMutation, useQuery } from "@tanstack/react-query";
import { dailyKeys } from "@/hooks/useDaily";
import { useInvalidatingMutation } from "@/hooks/useInvalidatingMutation";
import { api } from "@/lib/apiClient";
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

export function useGoogleCalendars(enabled: boolean) {
  return useQuery({
    queryKey: CALENDARS_KEY,
    queryFn: () => api.get<GoogleCalendarInfo[]>("/profile/google-calendar/calendars"),
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
