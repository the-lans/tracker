import { Layers } from "lucide-react";
import { useQueueSummary } from "@/hooks/useTasks";

/** Раздел 15.1: занятые слоты текущего пользователя и его очередь — над списком задач. */
export function QueueSummaryLine() {
  const { data: summary } = useQueueSummary();
  if (!summary) return null;
  return (
    <div className="flex items-center gap-1.5 px-5 pb-3 text-note text-text-2 lg:px-8">
      <Layers className="size-3.5 shrink-0 text-text-3" />
      <span>
        Слоты: {summary.occupied} из {summary.max_parallel_tasks} · в очереди {summary.ready} · ночью{" "}
        {summary.night_worker}
      </span>
    </div>
  );
}
