import { Archive, ArchiveRestore } from "lucide-react";

/**
 * Иконка «Архивировать / Разархивировать» в карточке (раздел 3.2 ТЗ:
 * используемый пайплайн или промт нельзя удалить — только архивировать).
 */
export function ArchiveToggleButton({
  name,
  archived,
  pending,
  onToggle,
}: {
  name: string;
  archived: boolean;
  pending: boolean;
  onToggle: () => void;
}) {
  const label = archived ? "Разархивировать" : "Архивировать";
  return (
    <button
      type="button"
      onClick={onToggle}
      disabled={pending}
      className="touch-target flex shrink-0 items-center justify-center text-text-3 hover:text-text disabled:opacity-50"
      aria-label={`${label} ${name}`}
      title={label}
    >
      {archived ? <ArchiveRestore className="size-4" /> : <Archive className="size-4" />}
    </button>
  );
}
