import { X } from "lucide-react";
import { SearchInput } from "@/components/common/inputs/SearchInput";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { HEADER_BUTTON } from "@/styles/classes";

export interface ArchiveFiltersValue {
  search: string;
  from: string;
  to: string;
}

/** Раздел 15.1: поиск по коду и названию и период завершения задачи. */
export function ArchiveFiltersBar({
  value,
  onChange,
  onReset,
}: {
  value: ArchiveFiltersValue;
  onChange: (patch: Partial<ArchiveFiltersValue>) => void;
  onReset: () => void;
}) {
  const filtered = Boolean(value.search || value.from || value.to);

  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-end">
      <SearchInput
        type="search"
        aria-label="Найти задачу по коду или названию"
        containerClassName="flex-1 sm:basis-64"
        placeholder="Код или название задачи..."
        value={value.search}
        onChange={(event) => onChange({ search: event.target.value })}
        onClear={() => onChange({ search: "" })}
      />
      <div className="grid grid-cols-2 gap-2 sm:flex">
        <div className="flex min-w-0 flex-col gap-1">
          <Label htmlFor="archive-from" className="text-meta font-normal text-text-3">
            Завершена с
          </Label>
          <Input
            id="archive-from"
            type="date"
            className="h-11 min-w-0 sm:w-40"
            value={value.from}
            max={value.to || undefined}
            onChange={(event) => onChange({ from: event.target.value })}
          />
        </div>
        <div className="flex min-w-0 flex-col gap-1">
          <Label htmlFor="archive-to" className="text-meta font-normal text-text-3">
            по
          </Label>
          <Input
            id="archive-to"
            type="date"
            aria-label="Завершена по"
            className="h-11 min-w-0 sm:w-40"
            value={value.to}
            min={value.from || undefined}
            onChange={(event) => onChange({ to: event.target.value })}
          />
        </div>
      </div>
      {filtered && (
        <button type="button" className={`${HEADER_BUTTON} h-11 self-start sm:self-end`} onClick={onReset}>
          <X className="size-4" />
          Сбросить
        </button>
      )}
    </div>
  );
}
