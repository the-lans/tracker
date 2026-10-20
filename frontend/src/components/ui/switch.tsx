import { forwardRef } from "react";
import * as SwitchPrimitive from "@radix-ui/react-switch";
import { cn } from "@/lib/utils";

export const Switch = forwardRef<
  React.ElementRef<typeof SwitchPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof SwitchPrimitive.Root>
>(({ className, ...props }, ref) => (
  <SwitchPrimitive.Root
    ref={ref}
    className={cn(
      // Трек остаётся 36×20, а зона нажатия расширена псевдоэлементом до 58×46
      // (раздел 15.3) — `touch-target` растянул бы сам трек в круг.
      "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border-[1.5px] border-text-3 bg-surface-2 transition-colors after:absolute after:-inset-x-3 after:-inset-y-[14px] after:content-[''] data-[state=checked]:border-accent data-[state=checked]:bg-accent disabled:opacity-50",
      className,
    )}
    {...props}
  >
    <SwitchPrimitive.Thumb className="block h-3.5 w-3.5 translate-x-0.5 rounded-full bg-white shadow transition-transform data-[state=checked]:translate-x-[18px]" />
  </SwitchPrimitive.Root>
));
Switch.displayName = "Switch";
