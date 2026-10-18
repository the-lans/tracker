import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";
import type { HTMLAttributes } from "react";

const badgeVariants = cva(
  "inline-flex items-center whitespace-nowrap rounded-full px-2.5 py-1 text-[11px] font-bold",
  {
    variants: {
      tone: {
        neutral: "bg-surface-2 text-text-2",
        accent: "bg-accent-tint text-accent-hov",
        info: "bg-info-tint text-info-text",
        warning: "bg-warning-tint text-warning-text",
        danger: "bg-danger-tint text-danger-text",
        success: "bg-success-tint text-success-text",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone, className }))} {...props} />;
}
