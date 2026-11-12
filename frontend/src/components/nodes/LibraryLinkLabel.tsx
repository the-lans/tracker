import { BookText } from "lucide-react";
import type { NodeItem } from "@/lib/types";

/** Раздел 7.6: нода пайплайна выполняет промт библиотеки — какой и не в архиве ли он. */
export function LibraryLinkLabel({ source }: { source: NodeItem | undefined }) {
  return (
    <div className="mt-0.5 flex min-w-0 items-center gap-1 text-caption text-accent">
      <BookText className="size-3.5 shrink-0" />
      <span className="truncate">Из библиотеки: {source?.name ?? "недоступный промт"}</span>
      {source?.is_archived && <span className="shrink-0 text-warning-text">· в архиве</span>}
    </div>
  );
}
