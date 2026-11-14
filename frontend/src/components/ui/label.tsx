import { forwardRef } from "react";
import * as LabelPrimitive from "@radix-ui/react-label";
import { cn } from "@/lib/utils";

/**
 * Подпись поля. `required` — красная «*» обязательного поля; она рисуется
 * псевдоэлементом, поэтому не входит в текст подписи и поиск поля по ней.
 */
export const Label = forwardRef<
  React.ElementRef<typeof LabelPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof LabelPrimitive.Root> & { required?: boolean }
>(({ className, required = false, ...props }, ref) => (
  <LabelPrimitive.Root
    ref={ref}
    data-required={required || undefined}
    className={cn(
      "mb-1 block text-meta font-bold text-text-3",
      required && "after:ml-0.5 after:text-danger after:content-['*']",
      className,
    )}
    {...props}
  />
));
Label.displayName = "Label";
