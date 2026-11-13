import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";

/** Значение пункта «Все …» внутри Select; наружу оно отдаётся как `undefined`. */
const ALL = "all";

/**
 * Фильтр списка по одному полю: первый пункт — «Все …» (`undefined`, фильтр
 * не задан), далее `values` в заданном порядке с подписями из `labels`.
 */
export function FilterSelect<T extends string>({
  value,
  onChange,
  values,
  labels,
  allLabel,
  label,
  className,
}: {
  value: T | undefined;
  onChange: (value: T | undefined) => void;
  values: readonly T[];
  labels: Record<T, string>;
  allLabel: string;
  /** Подпись поля для экранного диктора. */
  label: string;
  className?: string;
}) {
  return (
    <Select value={value ?? ALL} onValueChange={(next) => onChange(next === ALL ? undefined : (next as T))}>
      <SelectTrigger
        className={cn("w-40", className)}
        aria-label={label}
        // Длинная подпись в поле обрезается — целиком она видна в подсказке.
        title={value === undefined ? allLabel : labels[value]}
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ALL}>{allLabel}</SelectItem>
        {values.map((option) => (
          <SelectItem key={option} value={option}>
            {labels[option]}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
