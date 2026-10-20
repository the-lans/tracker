import { forwardRef } from "react";
import * as CheckboxPrimitive from "@radix-ui/react-checkbox";
import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

export const Checkbox = forwardRef<
  React.ElementRef<typeof CheckboxPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof CheckboxPrimitive.Root>
>(({ className, ...props }, ref) => (
  <CheckboxPrimitive.Root
    ref={ref}
    className={cn(
      // Зона нажатия 44px (как у `touch-target`) без раздувания самого квадрата.
      "relative flex size-5 shrink-0 before:absolute before:-inset-[14px] before:content-[''] items-center justify-center rounded-[5px] border-[1.5px] border-text-3 bg-surface data-[state=checked]:border-success data-[state=checked]:bg-success disabled:opacity-40",
      className,
    )}
    {...props}
  >
    <CheckboxPrimitive.Indicator>
      <Check className="size-3.5 text-on-accent" strokeWidth={3} />
    </CheckboxPrimitive.Indicator>
  </CheckboxPrimitive.Root>
));
Checkbox.displayName = "Checkbox";
