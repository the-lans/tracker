import { Pencil } from "lucide-react";

/** Иконка «Изменить» в карточке — открывает форму редактирования элемента. */
export function EditButton({ name, onClick }: { name: string; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-label={`Изменить ${name}`}
      title="Изменить"
      onClick={onClick}
      className="touch-target flex shrink-0 items-center justify-center text-text-3 hover:text-accent"
    >
      <Pencil className="size-4" />
    </button>
  );
}
