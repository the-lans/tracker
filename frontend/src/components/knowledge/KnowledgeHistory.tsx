import { Button } from "@/components/ui/button";
import type { KnowledgeVersion } from "@/lib/knowledge.types";
import { useAuth } from "@/hooks/useAuth";
import { useIsAdmin } from "@/hooks/useIsAdmin";
import { useUsers } from "@/hooks/useAdmin";

export function KnowledgeHistory({versions, currentVersion, onOpen, disabled}: {
  versions: KnowledgeVersion[];
  currentVersion: number;
  onOpen: (version: number) => void;
  disabled: boolean;
}) {
  const { user } = useAuth();
  const admin = useIsAdmin();
  const { data: users } = useUsers({ enabled: admin });
  return <details className="rounded-lg border border-border bg-surface p-3">
    <summary className="cursor-pointer font-bold text-text-2 hover:text-text">История изменений</summary>
    {versions.length === 0 && <p className="mt-3 text-sm text-text-3">История пока пуста.</p>}
    {versions.map((version) => <div key={version.version} className="flex flex-wrap items-center gap-2 border-t border-border py-3 first:mt-3">
      <span>v{version.version}{version.version === currentVersion ? " · текущая" : ""} · {new Date(version.created_at).toLocaleString()} · {version.created_by === user?.id ? "Вы" : users?.find((item) => item.id === version.created_by)?.email ?? "Другой пользователь"}{" "}
        {version.task_id && <a className="text-accent hover:underline" href={`/tasks/${version.task_id}`}>Задача</a>}
      </span>
      <Button variant="secondary" size="sm" disabled={disabled} onClick={() => onOpen(version.version)}>Открыть версию</Button>
    </div>)}
  </details>;
}
