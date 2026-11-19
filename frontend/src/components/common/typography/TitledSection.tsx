import type { ReactNode } from "react";
import { SectionTitle } from "@/components/common/typography/SectionTitle";
import { cn } from "@/lib/utils";

/**
 * Раздел окна или страницы с заголовком: содержимое под `SectionTitle`, соседние
 * разделы разделены чертой.
 */
export function TitledSection({
  title,
  className,
  children,
}: {
  title: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section
      className={cn(
        "border-t border-border pt-4 first:border-t-0 first:pt-0",
        className,
      )}
    >
      <SectionTitle className="mb-2">{title}</SectionTitle>
      {children}
    </section>
  );
}
