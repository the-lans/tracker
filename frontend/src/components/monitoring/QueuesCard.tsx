import { Badge } from "@/components/ui/badge";
import { CELERY_QUEUE_LABEL } from "@/lib/labels";
import type { ServerOverview } from "@/lib/monitoring.types";
import { plural } from "@/lib/utils";

/**
 * Раздел 15.5, 20.3: очереди Celery — сколько воркеров их слушает и сколько
 * сообщений ждёт в брокере; очередь ручных запросов к сессиям (раздел 7.3).
 */
export function QueuesCard({ overview }: { overview: ServerOverview }) {
  return (
    <div className="flex flex-col gap-3">
      <ul className="flex flex-col gap-2">
        {overview.queues.map((queue) => (
          <li key={queue.name} className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
            <span className="min-w-0 flex-1 font-bold text-text">
              {CELERY_QUEUE_LABEL[queue.name] ?? queue.name}
            </span>
            <Badge tone={queue.workers > 0 ? "success" : "danger"}>
              {queue.workers > 0
                ? `${queue.workers} ${plural(queue.workers, ["воркер", "воркера", "воркеров"])}`
                : "нет воркеров"}
            </Badge>
            <span className="text-small tabular-nums text-text-3">
              в очереди: {queue.pending ?? "—"}
            </span>
          </li>
        ))}
      </ul>
      <div className="border-t border-border pt-3 text-body">
        <span className="text-text-3">Ручные запросы к сессиям: </span>
        <span className="font-bold tabular-nums">{overview.manual_requests_queued}</span>
        <span className="text-text-3"> ждут, </span>
        <span className="font-bold tabular-nums">{overview.manual_requests_processing}</span>
        <span className="text-text-3"> выполняются</span>
      </div>
    </div>
  );
}
