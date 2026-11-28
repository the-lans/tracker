import { Label } from "@/components/ui/label";
import { useRepositories } from "@/hooks/useRepositories";

export function NodeTestFields({ repositoryId, check, script, onChange }: {
  repositoryId: string | null; check: string | null; script: boolean;
  onChange: (repositoryId: string | null, check: string | null) => void;
}) {
  const { data: repositories } = useRepositories();
  const selected = repositories?.find((repository) => repository.id === repositoryId);
  return <div className="flex flex-col gap-2">
    <div><Label htmlFor="node-test-repository">Тестовое окружение репозитория</Label>
      <select id="node-test-repository" className="w-full rounded border border-border bg-surface p-2" value={repositoryId ?? ""}
        onChange={(event) => onChange(event.target.value || null, null)}>
        <option value="">Без выбранного окружения</option>
        {repositories?.filter((repository) => repository.test_profile).map((repository) =>
          <option key={repository.id} value={repository.id}>{repository.name}</option>)}
      </select></div>
    {repositoryId && script && <div><Label htmlFor="node-test-check">Проверка</Label>
      <select id="node-test-check" className="w-full rounded border border-border bg-surface p-2" value={check ?? ""}
        onChange={(event) => onChange(repositoryId, event.target.value || null)}>
        <option value="">Выберите проверку</option>
        {Object.keys(selected?.test_profile?.commands ?? {}).map((name) => <option key={name} value={name}>{name}</option>)}
      </select></div>}
    {repositoryId && !script && <p className="text-small text-text-3">Агент получает инструменты запуска проверок. Порядок запуска задайте в промпте.</p>}
  </div>;
}
