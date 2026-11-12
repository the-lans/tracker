import { useSearchParams } from "react-router-dom";

export const TAB_PARAM = "tab";

/**
 * Активная вкладка страницы в адресе (`?tab=`): ссылка и перезагрузка
 * открывают ту же вкладку. Неизвестное значение — вкладка по умолчанию.
 */
export function useUrlTab<T extends string>(
  values: readonly T[],
  defaultValue: T,
): [T, (value: string) => void] {
  const [searchParams, setSearchParams] = useSearchParams();
  const requested = searchParams.get(TAB_PARAM);
  const tab = values.find((value) => value === requested) ?? defaultValue;
  const setTab = (value: string) => setSearchParams({ [TAB_PARAM]: value }, { replace: true });
  return [tab, setTab];
}
