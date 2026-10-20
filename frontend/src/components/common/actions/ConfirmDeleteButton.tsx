import { useState } from "react";
import { Trash2 } from "lucide-react";
import { ConfirmDialog } from "@/components/common/dialogs/ConfirmDialog";
import { cn } from "@/lib/utils";

/**
 * Кнопка удаления с подтверждением: запрос уходит только после явного
 * «Удалить» в диалоге, где назван удаляемый элемент.
 */
export function ConfirmDeleteButton({
  kind,
  name,
  onConfirm,
  pending = false,
  iconClassName = "size-4",
}: {
  /** Что удаляется, в винительном падеже: «пайплайн», «переменную». */
  kind: string;
  name: string;
  onConfirm: () => void;
  pending?: boolean;
  iconClassName?: string;
}) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        type="button"
        aria-label={`Удалить ${name}`}
        disabled={pending}
        onClick={() => setOpen(true)}
        className="touch-target flex shrink-0 items-center justify-center text-text-3 hover:text-danger disabled:opacity-50"
      >
        <Trash2 className={cn(iconClassName)} />
      </button>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title={`Удалить ${kind}?`}
        description={
          <>
            <span className="font-bold text-text [overflow-wrap:anywhere]">«{name}»</span> — удаление
            нельзя отменить.
          </>
        }
        confirmLabel="Удалить"
        danger
        pending={pending}
        onConfirm={() => {
          setOpen(false);
          onConfirm();
        }}
      />
    </>
  );
}
