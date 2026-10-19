import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useRepositories } from "@/hooks/useRepositories";
import { RepositoryRole, type TaskRepositoryAttach } from "@/lib/types";

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
    return <div className="text-[12.5px] text-text-3">Загрузка репозиториев…</div>;
  }
  if (!repositories?.length) {
    return (
      <div className="text-[12.5px] text-text-3">
        Репозиториев пока нет — добавьте их в разделе «Репозитории».
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {repositories.map((repository) => {
        const attached = selected.get(repository.id);
        return (
          <div key={repository.id} className="rounded-lg border border-border px-2.5 py-2">
            <label className="flex items-center gap-2.5 text-[13px] font-bold">
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
                    <SelectItem value={RepositoryRole.READ_WRITE}>read-write</SelectItem>
                    <SelectItem value={RepositoryRole.READ_ONLY}>read-only</SelectItem>
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
