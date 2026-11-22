import { useCallback, useEffect, useState } from "react";
import {
  SIDEBAR_DEFAULT_WIDTH,
  isSidebarCompact,
  normalizeSidebarWidth,
  readStoredSidebarWidth,
  storeSidebarWidth,
} from "@/lib/sidebarWidth";

/** Ширина бокового меню: хранится в браузере, при очень малой ширине меню показывает только значки. */
export function useSidebarWidth() {
  const [width, setWidthState] = useState<number>(() => readStoredSidebarWidth());

  useEffect(() => {
    storeSidebarWidth(width);
  }, [width]);

  const setWidth = useCallback((next: number) => setWidthState(normalizeSidebarWidth(next)), []);
  const reset = useCallback(() => setWidthState(SIDEBAR_DEFAULT_WIDTH), []);

  return { width, compact: isSidebarCompact(width), setWidth, reset };
}
