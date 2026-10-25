import type { ReactNode } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";

/** Что открыто в диалоге формы: новая запись, существующая или ничего. */
export type EditTarget<T> = T | "new" | null;

/** Диалог создания/редактирования записи справочника; форма получает запись (`undefined` — новая). */
export function EntityFormDialog<T>({
  target,
  onClose,
  createTitle,
  editTitle,
  contentClassName,
  children,
}: {
  target: EditTarget<T>;
  onClose: () => void;
  createTitle: string;
  editTitle: string;
  contentClassName?: string;
  children: (item: T | undefined, close: () => void) => ReactNode;
}) {
  return (
    <Dialog open={target !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className={contentClassName}>
        <DialogHeader>
          <DialogTitle>{target === "new" ? createTitle : editTitle}</DialogTitle>
        </DialogHeader>
        {target !== null && children(target === "new" ? undefined : target, onClose)}
      </DialogContent>
    </Dialog>
  );
}
