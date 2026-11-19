import type { ReactNode } from "react";
import { cva } from "class-variance-authority";
import { cn } from "@/lib/utils";

const chipVariants = cva("rounded-full font-bold disabled:opacity-50", {
  variants: {
    size: {
      // Фильтр списка: на телефоне ниже, зона нажатия та же.
      default: "touch-target touch-compact bg-surface-2 px-3.5 py-1.5 text-body text-text",
      compact: "touch-hit min-h-9 bg-surface-2 px-2.5 py-1 text-small text-text sm:px-3.5 sm:py-1.5 sm:text-body",
      // В строке карточки: зона нажатия 44×44 — без увеличения самой кнопки.
      sm: "touch-hit border border-border px-2.5 py-0.5 max-sm:px-2 text-caption text-text-2",
    },
    pressed: { true: "", false: "" },
  },
  compoundVariants: [
    { size: "default", pressed: true, className: "bg-text text-bg" },
    { size: "compact", pressed: true, className: "bg-text text-bg" },
    { size: "sm", pressed: true, className: "border-accent-border bg-accent-tint text-accent-hov" },
  ],
  defaultVariants: { size: "default", pressed: false },
});

/** Кнопка-переключатель «пилюлей»: фильтр списка, отметка задачи на день. */
export function ToggleChip({
  pressed,
  onToggle,
  children,
  size = "default",
  disabled = false,
  title,
  label,
}: {
  pressed: boolean;
  onToggle: () => void;
  children: ReactNode;
  size?: "default" | "sm" | "compact";
  disabled?: boolean;
  title?: string;
  /** Подпись для экранного диктора, если текста кнопки мало. */
  label?: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      aria-label={label}
      title={title}
      disabled={disabled}
      onClick={onToggle}
      className={cn(chipVariants({ size, pressed }))}
    >
      {children}
    </button>
  );
}
