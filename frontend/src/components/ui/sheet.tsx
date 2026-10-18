import { forwardRef } from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

/** Bottom sheet для мобильных раскладок (раздел 15.3 ТЗ) — выезжает снизу,
 * а не модальное окно, дублирующее десктопную раскладку. */
export const Sheet = DialogPrimitive.Root;
export const SheetTrigger = DialogPrimitive.Trigger;

export const SheetContent = forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content>
>(({ className, children, ...props }, ref) => (
  <DialogPrimitive.Portal>
    <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/40" />
    <DialogPrimitive.Content
      ref={ref}
      className={cn(
        "fixed inset-x-0 bottom-0 z-50 max-h-[85vh] overflow-y-auto rounded-t-xl border-t border-border bg-surface p-5 pb-8 shadow-xl",
        "data-[state=open]:animate-in data-[state=open]:slide-in-from-bottom",
        className,
      )}
      {...props}
    >
      <div className="mx-auto mb-3 h-1.5 w-10 rounded-full bg-border" />
      {children}
      <DialogPrimitive.Close className="absolute right-4 top-4 touch-target flex items-center justify-center rounded-md text-text-3 hover:text-text">
        <X className="size-4" />
      </DialogPrimitive.Close>
    </DialogPrimitive.Content>
  </DialogPrimitive.Portal>
));
SheetContent.displayName = "SheetContent";

export const SheetTitle = DialogPrimitive.Title;
