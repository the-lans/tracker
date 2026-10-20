import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useRepositories } from "@/hooks/useRepositories";
import { RepositoryRole, type TaskRepositoryAttach } from "@/lib/types";
import { REPOSITORY_ROLE_LABEL } from "@/lib/labels";
import { EmptyState } from "@/components/common/feedback/EmptyState";

const DEFAULT_BASE_BRANCH = "main";

/** Раздел 1.2 (сценарий 1): репозитории задачи с ролью и базовой веткой. */
export function TaskRepositoryPicker({
  value,
  onChange,
}: {
  value: TaskRepositoryAttach[];
  onChange: (value: TaskRepositoryAttach[]) => void;
}) {
  const { data: repositories, isLoading } = useRepositories();
  const selected = new Map(value.map((attached) => [attached.repository_id, attached]));

  function toggle(repositoryId: string, checked: boolean) {
    if (checked) {
      onChange([
        ...value,
        { repository_id: repositoryId, role: RepositoryRole.READ_WRITE, base_branch: DEFAULT_BASE_BRANCH },
      ]);
    } else {
      onChange(value.filter((attached) => attached.repository_id !== repositoryId));
    }
  }

  function update(repositoryId: string, patch: Partial<TaskRepositoryAttach>) {
    onChange(
      value.map((attached) =>
        attached.repository_id === repositoryId ? { ...attached, ...patch } : attached,
      ),
    );
  }

  if (isLoading) {
    return <div className="text-note text-text-3">Загрузка репозиториев…</div>;
  }
  if (!repositories?.length) {
    return (
      <EmptyState
        compact
        title="Репозиториев пока нет"
        hint="Подключите репозиторий в разделе «Репозитории» кнопкой «+ Репозиторий» (Git-адрес и deploy-ключ) — затем его можно будет выбрать здесь."
      />
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {repositories.map((repository) => {
        const attached = selected.get(repository.id);
        return (
          <div key={repository.id} className="rounded-lg border border-border px-2.5 py-2">
            <label className="flex items-center gap-2.5 text-body font-bold">
              <Checkbox
                checked={Boolean(attached)}
                onCheckedChange={(checked) => toggle(repository.id, checked === true)}
              />
              {repository.name}
            </label>
            {attached && (
              <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
                <Select
                  value={attached.role}
                  onValueChange={(role) => update(repository.id, { role: role as RepositoryRole })}
                >
                  <SelectTrigger aria-label="Роль репозитория">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={RepositoryRole.READ_WRITE}>{REPOSITORY_ROLE_LABEL[RepositoryRole.READ_WRITE]}</SelectItem>
                    <SelectItem value={RepositoryRole.READ_ONLY}>{REPOSITORY_ROLE_LABEL[RepositoryRole.READ_ONLY]}</SelectItem>
                  </SelectContent>
                </Select>
                <Input
                  aria-label="Базовая ветка"
                  placeholder="Базовая ветка"
                  value={attached.base_branch}
                  onChange={(event) => update(repository.id, { base_branch: event.target.value })}
                  required
                />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
