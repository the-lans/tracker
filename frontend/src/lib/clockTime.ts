/** Время API «ЧЧ:ММ:СС» ↔ «ЧЧ:ММ» поля `type="time"` и подписей. */

export function clockTime(value: string): string {
  return value.slice(0, 5);
}

/** Необязательное время: `null` — пустое поле. */
export function optionalClockTime(value: string | null | undefined): string {
  return value ? clockTime(value) : "";
}

export function apiClockTime(field: string): string {
  return `${field}:00`;
}

/** Пустое поле — `null`: время не задано. */
export function optionalApiClockTime(field: string): string | null {
  return field ? apiClockTime(field) : null;
}
