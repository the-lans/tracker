import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { ConfirmDeleteButton } from "@/components/common/actions/ConfirmDeleteButton";
import { QueryState } from "@/components/common/feedback/QueryState";
import {
  useDisconnectGoogleCalendar,
  useGoogleCalendar,
  useGoogleCalendars,
  useSetGoogleCalendars,
  useStartGoogleCalendarLogin,
  useSyncGoogleCalendar,
} from "@/hooks/useGoogleCalendar";
import type { GoogleCalendarConnection } from "@/lib/daily.types";
import { toastError } from "@/lib/errors";
import { GOOGLE_CALENDAR_STATUS_LABEL, GOOGLE_CALENDAR_STATUS_TONE } from "@/lib/labels";
import { formatDateTime } from "@/lib/utils";
import { WRAP_ROW } from "@/styles/classes";

/** Параметр, с которым трекер возвращает браузер в профиль после входа у Google. */
const LOGIN_RESULT_PARAM = "calendar";
const LOGIN_RESULT_TOAST: Record<string, () => void> = {
  connected: () => toast.success("Google Calendar подключён"),
  error: () => toast.error("Не удалось подключить Google Calendar"),
};

/** Итог входа у Google — тостом один раз; параметр убирается из адреса. */
function useLoginResultToast() {
  const [searchParams, setSearchParams] = useSearchParams();
  const result = searchParams.get(LOGIN_RESULT_PARAM);

  useEffect(() => {
    if (!result) return;
    LOGIN_RESULT_TOAST[result]?.();
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete(LOGIN_RESULT_PARAM);
        return next;
      },
      { replace: true },
    );
  }, [result, setSearchParams]);
}

function LoginButton({ label }: { label: string }) {
  const login = useStartGoogleCalendarLogin();
  return (
    <Button
      className="self-start"
      disabled={login.isPending}
      onClick={() =>
        login.mutate(undefined, {
          onSuccess: ({ url }) => window.location.assign(url),
          onError: toastError("Не удалось начать вход в Google"),
        })}
    >
      {label}
    </Button>
  );
}

/** Календари аккаунта, события которых попадают в «Дейли». */
function CalendarSelection({ connection }: { connection: GoogleCalendarConnection }) {
  const { data: calendars, isLoading, isError } = useGoogleCalendars(true);
  const setCalendars = useSetGoogleCalendars();
  const [selected, setSelected] = useState(connection.calendar_ids);
  const changed = selected.join() !== connection.calendar_ids.join();

  function toggle(id: string, checked: boolean) {
    setSelected((prev) => (checked ? [...prev, id] : prev.filter((item) => item !== id)));
  }

  return (
    <QueryState isLoading={isLoading} isError={isError} errorLabel="Не удалось загрузить календари">
      <fieldset className="flex flex-col gap-1">
        <legend className="mb-1 text-small font-bold text-text-2">Календари</legend>
        {(calendars ?? []).map((calendar) => {
          const { id } = calendar;
          return (
            <label key={id} className="flex min-h-11 items-center gap-2.5 text-note text-text-2">
              <Checkbox
                checked={selected.includes(id)}
                onCheckedChange={(value) => toggle(id, value === true)}
              />
              <span className="min-w-0 break-words">
                {calendar.summary}
                {calendar.primary && <span className="text-text-3"> · основной</span>}
              </span>
            </label>
          );
        })}
        <Button
          size="sm"
          variant="secondary"
          className="mt-1 self-start"
          disabled={!changed || selected.length === 0 || setCalendars.isPending}
          onClick={() =>
            setCalendars.mutate(selected, {
              onSuccess: () => toast.success("Календари сохранены"),
              onError: toastError("Не удалось сохранить календари"),
            })}
        >
          Сохранить выбор
        </Button>
      </fieldset>
    </QueryState>
  );
}

function ConnectedCalendar({ connection }: { connection: GoogleCalendarConnection }) {
  const sync = useSyncGoogleCalendar();
  const disconnect = useDisconnectGoogleCalendar();
  const connected = connection.status === "connected";

  return (
    <div className="flex flex-col gap-3">
      <div className={WRAP_ROW}>
        <span className="min-w-0 break-all font-bold">{connection.google_email}</span>
        <Badge tone={GOOGLE_CALENDAR_STATUS_TONE[connection.status]}>
          {GOOGLE_CALENDAR_STATUS_LABEL[connection.status]}
        </Badge>
        <span className="ml-auto">
          <ConfirmDeleteButton
            kind="подключение к Google Calendar"
            name={connection.google_email}
            pending={disconnect.isPending}
            onConfirm={() => disconnect.mutate(undefined, { onError: toastError("Не удалось отключить календарь") })}
          />
        </span>
      </div>
      <div className="text-small text-text-3">
        Синхронизирован: {formatDateTime(connection.last_synced_at)}
        {connection.last_error && <div className="text-warning-text">{connection.last_error}</div>}
      </div>
      {connected ? (
        <>
          <CalendarSelection key={connection.calendar_ids.join()} connection={connection} />
          <Button
            variant="secondary"
            className="self-start"
            disabled={sync.isPending}
            onClick={() =>
              sync.mutate(undefined, {
                onSuccess: ({ synced, events }) =>
                  synced ? toast.success(`Загружено событий: ${events}`) : toast.error("Календарь не обновлён"),
                onError: toastError("Не удалось обновить календарь"),
              })}
          >
            <RefreshCw className="size-4" /> Обновить сейчас
          </Button>
        </>
      ) : (
        <LoginButton label="Войти снова" />
      )}
    </div>
  );
}

/**
 * Раздел 19.8: события Google Calendar в «Дейли» — только чтение, раз в
 * 15 минут и кнопкой. Подключение личное.
 */
export function GoogleCalendarCard() {
  useLoginResultToast();
  const { data: connection, isLoading, isError } = useGoogleCalendar();

  return (
    <Card>
      <CardTitle>
        <span>Google Calendar</span>
      </CardTitle>
      <div className="mb-3 text-small text-text-3">
        События выбранных календарей за 7 прошлых дней, сегодня и завтра попадают в «Дейли» и в план на день.
      </div>
      <QueryState isLoading={isLoading} isError={isError} errorLabel="Не удалось загрузить подключение">
        {connection ? <ConnectedCalendar connection={connection} /> : <LoginButton label="Подключить" />}
      </QueryState>
    </Card>
  );
}
