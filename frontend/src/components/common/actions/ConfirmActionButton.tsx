import { useState, type ReactNode } from "react";
import { Button, type ButtonProps } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/common/dialogs/ConfirmDialog";

/**
 * Кнопка действия, которое теряет данные (пересборка, сброс): запрос уходит
 * только после подтверждения в диалоге с описанием последствий.
 */
export function ConfirmActionButton({
  children,
  title,
  description,
  confirmLabel,
  onConfirm,
  pending = false,
  disabled = false,
  variant = "secondary",
}: {
  children: ReactNode;
  title: string;
  description: ReactNode;
  confirmLabel: string;
  onConfirm: () => void;
  pending?: boolean;
  disabled?: boolean;
  variant?: ButtonProps["variant"];
}) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <Button variant={variant} disabled={disabled || pending} onClick={() => setOpen(true)}>
        {children}
      </Button>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title={title}
        description={description}
        confirmLabel={confirmLabel}
        pending={pending}
        onConfirm={() => {
          setOpen(false);
          onConfirm();
        }}
      />
    </>
  );
}
