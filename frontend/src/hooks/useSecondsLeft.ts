import { useEffect, useState } from "react";

const TICK_MS = 1000;

/** Секунд до `deadline`, обновляется раз в секунду; `null` — срока нет. */
export function useSecondsLeft(deadline: string | undefined): number | null {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!deadline) return;
    const timer = setInterval(() => setNow(Date.now()), TICK_MS);
    return () => clearInterval(timer);
  }, [deadline]);

  if (!deadline) return null;
  return Math.max(0, Math.ceil((Date.parse(deadline) - now) / TICK_MS));
}
