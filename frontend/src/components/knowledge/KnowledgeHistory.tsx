import { Button } from "@/components/ui/button";
import type { KnowledgeVersion } from "@/lib/knowledge.types";

export function KnowledgeHistory({versions, onOpen, disabled}: {
  versions: KnowledgeVersion[];
  onOpen: (version: number) => void;
  disabled: boolean;
}) {
  return <details>
    <summary>История изменений</summary>
    {versions.map((version) => <div key={version.version} className="flex flex-wrap gap-2 py-1">
      <span>v{version.version} · {new Date(version.created_at).toLocaleString()} · {version.created_by}{" "}
        {version.task_id && <a href={`/tasks/${version.task_id}`}>Задача</a>}
      </span>
      <Button disabled={disabled} onClick={() => onOpen(version.version)}>Открыть версию</Button>
    </div>)}
  </details>;
}
