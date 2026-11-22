import { useEffect, useRef, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

interface ClampedContentProps {
  children: ReactNode;
  /** Высота, выше которой содержимое обрезается, px. */
  maxHeight?: number;
  /** Что показать под обрезанным содержимым (например, кнопку «Открыть полностью»); у короткого — ничего. */
  renderMore?: () => ReactNode;
  className?: string;
}

/**
 * Содержимое с ограничением по высоте: длинное обрезается с затуханием снизу,
 * короткое показывается целиком. Высота перемеряется при изменении содержимого —
 * например, когда подгрузились картинки описания.
 */
export function ClampedContent({ children, maxHeight = 192, renderMore, className }: ClampedContentProps) {
  const inner = useRef<HTMLDivElement>(null);
  const [clipped, setClipped] = useState(false);

  useEffect(() => {
    const element = inner.current;
    if (element === null) return;
    const measure = () => setClipped(element.scrollHeight > maxHeight + 1);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [maxHeight]);

  return (
    <div className={className}>
      <div className="relative overflow-hidden" style={{ maxHeight }}>
        <div ref={inner}>{children}</div>
        {clipped && (
          <div
            aria-hidden
            data-testid="clamped-fade"
            className={cn("pointer-events-none absolute inset-x-0 bottom-0 h-12 bg-gradient-to-t from-surface to-transparent")}
          />
        )}
      </div>
      {clipped && renderMore?.()}
    </div>
  );
}
