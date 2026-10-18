import { forwardRef, type HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export const Card = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn("rounded-lg border border-border bg-surface p-4", className)}
      {...props}
    />
  ),
);
Card.displayName = "Card";

export const CardTitle = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn(
        "mb-2.5 flex items-center justify-between text-[12.5px] font-extrabold text-text-2",
        className,
      )}
      {...props}
    />
  ),
);
CardTitle.displayName = "CardTitle";
