import { forwardRef, type InputHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        "h-10 w-full short:h-9 touch-target rounded-md border border-border bg-surface px-3 text-sm text-text placeholder:text-text-3 focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50 aria-invalid:border-danger aria-invalid:focus-visible:outline-danger",
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = "Input";

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...props }, ref) => (
    <textarea
      ref={ref}
      className={cn(
        "w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-text placeholder:text-text-3 focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50 aria-invalid:border-danger aria-invalid:focus-visible:outline-danger",
        className,
      )}
      {...props}
    />
  ),
);
Textarea.displayName = "Textarea";
