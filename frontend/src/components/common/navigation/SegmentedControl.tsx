import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

/** Выбор одного значения из нескольких кнопками-сегментами (период, режим показа). */
export function SegmentedControl<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: Record<T, string>;
  onChange: (value: T) => void;
  /** Подпись группы для экранного диктора. */
  label: string;
}) {
  return (
    <Tabs value={value} onValueChange={(next) => onChange(next as T)}>
      <TabsList aria-label={label}>
        {(Object.keys(options) as T[]).map((option) => (
          <TabsTrigger key={option} value={option}>
            {options[option]}
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  );
}
