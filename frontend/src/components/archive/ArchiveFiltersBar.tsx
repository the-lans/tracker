import { Search, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

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
      <label className="flex min-h-11 min-w-0 flex-1 items-center gap-2 rounded-md border border-border bg-surface-2 px-3 text-body-lg text-text-3 sm:basis-64">
        <Search className="size-4 shrink-0" />
        <input
          type="search"
          aria-label="Найти задачу по коду или названию"
          className="h-11 min-w-0 flex-1 bg-transparent text-text outline-none placeholder:text-text-3"
          placeholder="Код или название задачи..."
          value={value.search}
          onChange={(event) => onChange({ search: event.target.value })}
        />
      </label>
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
        <Button variant="ghost" className="h-11 self-start sm:self-end" onClick={onReset}>
          <X className="size-4" />
          Сбросить
        </Button>
      )}
    </div>
  );
}
