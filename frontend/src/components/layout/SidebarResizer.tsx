import { useRef, type KeyboardEvent, type PointerEvent } from "react";
import {
  SIDEBAR_COMPACT_WIDTH,
  SIDEBAR_DEFAULT_WIDTH,
  SIDEBAR_MAX_WIDTH,
  stepSidebarWidth,
} from "@/lib/sidebarWidth";
import { cn } from "@/lib/utils";

interface Props {
  width: number;
  onChange: (width: number) => void;
  onReset: () => void;
}

/** Полоса на правой границе меню: тянется мышью или пальцем, стрелками, двойной щелчок — ширина по умолчанию. */
export function SidebarResizer({ width, onChange, onReset }: Props) {
  const drag = useRef<{ startX: number; startWidth: number } | null>(null);

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    drag.current = { startX: event.clientX, startWidth: width };
    event.currentTarget.setPointerCapture?.(event.pointerId);
    document.body.style.userSelect = "none";
    document.body.style.cursor = "col-resize";
  };

  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    onChange(drag.current.startWidth + event.clientX - drag.current.startX);
  };

  const stopDrag = (event: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    drag.current = null;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    document.body.style.userSelect = "";
    document.body.style.cursor = "";
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "ArrowRight") onChange(stepSidebarWidth(width, 1));
    else if (event.key === "ArrowLeft") onChange(stepSidebarWidth(width, -1));
    else if (event.key === "Home") onChange(SIDEBAR_COMPACT_WIDTH);
    else if (event.key === "End") onChange(SIDEBAR_MAX_WIDTH);
    else return;
    event.preventDefault();
  };

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Ширина меню"
      aria-valuemin={SIDEBAR_COMPACT_WIDTH}
      aria-valuemax={SIDEBAR_MAX_WIDTH}
      aria-valuenow={width}
      tabIndex={0}
      title="Потяните, чтобы изменить ширину меню; двойной щелчок — по умолчанию"
      className={cn(
        "group absolute inset-y-0 -right-4 z-10 w-4 cursor-col-resize touch-none select-none outline-none",
        "focus-visible:[&>span]:bg-accent",
      )}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={stopDrag}
      onPointerCancel={stopDrag}
      onDoubleClick={width === SIDEBAR_DEFAULT_WIDTH ? undefined : onReset}
      onKeyDown={onKeyDown}
    >
      {/* Зона нажатия — снаружи меню, чтобы не перекрывать его полосу прокрутки; линия и «ручка» стоят на самой границе. */}
      <span className="absolute inset-y-0 left-0 w-[3px] -translate-x-1/2 bg-border transition-colors group-hover:bg-accent group-active:bg-accent" />
      <span
        aria-hidden
        className="absolute left-0 top-1/2 h-16 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full border border-surface bg-text-3 transition-colors group-hover:bg-accent group-active:bg-accent"
      />
    </div>
  );
}
