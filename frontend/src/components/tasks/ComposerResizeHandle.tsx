import { useRef, type RefObject } from "react";
import { Grip } from "lucide-react";

const MIN_HEIGHT = 64;

export function ComposerResizeHandle({ fieldRef, onResize }: {
  fieldRef: RefObject<HTMLTextAreaElement | null>;
  onResize: (height: number) => void;
}) {
  const drag = useRef<{ pointerId: number; y: number; height: number } | null>(null);

  function resize(height: number) {
    onResize(Math.max(MIN_HEIGHT, Math.min(height, Math.max(MIN_HEIGHT, window.innerHeight * 0.55))));
  }

  return (
    <button
      type="button"
      aria-label="Изменить высоту поля ввода"
      title="Потяните вверх или вниз; с клавиатуры используйте стрелки"
      className="absolute right-0 top-0 flex size-7 touch-none cursor-ns-resize items-center justify-center rounded-tr-md text-text-3 hover:bg-surface-2 hover:text-text focus-visible:outline-2 focus-visible:outline-accent"
      onPointerDown={(event) => {
        if (event.button !== 0 || !fieldRef.current) return;
        event.preventDefault();
        drag.current = { pointerId: event.pointerId, y: event.clientY, height: fieldRef.current.getBoundingClientRect().height };
        event.currentTarget.setPointerCapture(event.pointerId);
      }}
      onPointerMove={(event) => {
        if (drag.current?.pointerId === event.pointerId) resize(drag.current.height + drag.current.y - event.clientY);
      }}
      onPointerUp={(event) => { if (drag.current?.pointerId === event.pointerId) drag.current = null; }}
      onPointerCancel={() => { drag.current = null; }}
      onLostPointerCapture={() => { drag.current = null; }}
      onKeyDown={(event) => {
        if ((event.key !== "ArrowUp" && event.key !== "ArrowDown") || !fieldRef.current) return;
        event.preventDefault();
        resize(fieldRef.current.getBoundingClientRect().height + (event.key === "ArrowUp" ? 24 : -24));
      }}
    >
      <Grip className="size-4" aria-hidden="true" />
    </button>
  );
}
