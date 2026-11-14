import { Pause } from "lucide-react";
import { cn } from "@/lib/utils";

export function PauseAfterButton({
  name, pressed, disabled, onChange,
}: {
  name: string;
  pressed: boolean;
  disabled: boolean;
  onChange: (pauseAfter: boolean) => void;
}) {
  return (
    <button
      type="button"
      aria-label={`Пауза после ноды ${name}`}
      aria-pressed={pressed}
      title="Остановиться после этой ноды, чтобы продолжить диалог"
      disabled={disabled}
      onClick={() => onChange(!pressed)}
      className={cn(
        "touch-hit flex size-6 shrink-0 items-center justify-center rounded-md text-text-3 disabled:opacity-50",
        pressed && "bg-accent-tint text-accent",
      )}
    >
      <Pause className="size-3.5" />
    </button>
  );
}
