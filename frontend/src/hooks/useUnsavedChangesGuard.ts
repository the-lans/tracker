import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

/** Защита несохранённого текста при смене выбора и переходах по ссылкам. */
export function useUnsavedChangesGuard(dirty: boolean) {
  const navigate = useNavigate();
  const [pending, setPending] = useState<(() => void) | null>(null);

  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (dirty) { event.preventDefault(); event.returnValue = ""; }
    };
    const onLink = (event: MouseEvent) => {
      if (!dirty || event.ctrlKey || event.metaKey || event.shiftKey || event.button !== 0) return;
      const link = event.target instanceof Element ? event.target.closest("a[href]") : null;
      if (!(link instanceof HTMLAnchorElement) || link.origin !== location.origin || link.target === "_blank") return;
      event.preventDefault(); event.stopPropagation();
      setPending(() => () => navigate(link.pathname + link.search + link.hash));
    };
    window.addEventListener("beforeunload", beforeUnload);
    window.addEventListener("click", onLink, true);
    return () => {
      window.removeEventListener("beforeunload", beforeUnload);
      window.removeEventListener("click", onLink, true);
    };
  }, [dirty, navigate]);

  return {
    pending: pending !== null,
    guard: (action: () => void) => {
      if (dirty) setPending(() => action);
      else action();
    },
    cancel: () => setPending(null),
    confirm: () => { pending?.(); setPending(null); },
  };
}
