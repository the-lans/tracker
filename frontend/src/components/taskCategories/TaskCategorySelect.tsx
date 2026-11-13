import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { TaskCategory } from "@/lib/types";

/** Значение пункта «Без категории» внутри Select; наружу отдаётся как `null`. */
const NO_CATEGORY = "none";
export const NO_CATEGORY_LABEL = "Без категории";

/** Раздел 15.7: выбор категории задачи — в форме новой задачи и на странице задачи. */
export function TaskCategorySelect({
  id,
  value,
  categories,
  disabled,
  onChange,
}: {
  id?: string;
  value: string | null;
  categories: readonly TaskCategory[];
  disabled?: boolean;
  onChange: (categoryId: string | null) => void;
}) {
  return (
    <Select
      value={value ?? NO_CATEGORY}
      disabled={disabled}
      onValueChange={(choice) => onChange(choice === NO_CATEGORY ? null : choice)}
    >
      <SelectTrigger id={id} aria-label="Категория">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={NO_CATEGORY}>{NO_CATEGORY_LABEL}</SelectItem>
        {categories.map((category) => (
          <SelectItem key={category.id} value={category.id}>
            {category.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
