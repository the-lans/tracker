import { useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { useRepositories } from "@/hooks/useRepositories";
import { useTaskRepositories } from "@/hooks/useTasks";
import { useStartTestRun, useTestRunAction, useTestRuns, useTestRun } from "@/hooks/useTestRuns";
import { toastError } from "@/lib/errors";

const STATUSES: Record<string, string> = {
  queued: "В очереди", agent: "CI-агент", preparing: "Подготовка", running: "Выполняется",
  passed: "Успешно", failed: "Ошибка", cancelled: "Остановлено", timed_out: "Таймаут",
};
const CLEANUP: Record<string, string> = {
  pending: "Ожидает очистки", running: "Очистка", done: "Окружение удалено", failed: "Ошибка очистки",
};
export function TaskTestsPanel({ taskId, header }: { taskId: string; header?: ReactNode }) {
  const { data: runs, isLoading, error } = useTestRuns(taskId);
  const { data: taskRepositories } = useTaskRepositories(taskId);
  const { data: repositories } = useRepositories();
  const [repositoryId, setRepositoryId] = useState("");
  const [check, setCheck] = useState("");
  const start = useStartTestRun(taskId);
  const action = useTestRunAction(taskId);
  const available = (repositories ?? []).filter((repository) =>
    repository.test_profile && taskRepositories?.some((item) => item.repository_id === repository.id));
  const selected = available.find((item) => item.id === repositoryId) ?? available[0];
  const checks = Object.keys(selected?.test_profile?.commands ?? {});
  const selectedCheck = checks.includes(check) ? check : (checks[0] ?? "");
  return <section className="flex min-h-0 w-full flex-col">
    <div className="border-b border-border p-3">{header}</div>
    <div className="flex flex-col gap-4 overflow-auto p-4">
      <div className="flex flex-wrap items-end gap-3">
        <div><Label htmlFor="test-repository">Репозиторий</Label>
          <select id="test-repository" className="rounded border border-border bg-surface p-2" value={selected?.id ?? ""}
            onChange={(e) => setRepositoryId(e.target.value)}>
            {available.map((repository) => <option key={repository.id} value={repository.id}>{repository.name}</option>)}
          </select></div>
        <div><Label htmlFor="test-check">Проверка</Label>
          <select id="test-check" className="rounded border border-border bg-surface p-2" value={selectedCheck} onChange={(e) => setCheck(e.target.value)}>
            {checks.map((name) => <option key={name} value={name}>{name}</option>)}
          </select></div>
        <Button disabled={!selected || !selectedCheck || start.isPending} onClick={() => selected && start.mutate({
          repository_id: selected.id, check: selectedCheck, idempotency_key: crypto.randomUUID(),
        }, { onError: toastError("Не удалось запустить проверку") })}>Запустить тесты</Button>
      </div>
      {!available.length && <p>Настройте тестирование у репозитория, привязанного к задаче.</p>}
      {isLoading && <p>Загрузка прогонов…</p>}
      {error && <p role="alert">Не удалось загрузить прогоны</p>}
      {runs?.map((run) => <article key={run.id} className="rounded border border-border p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <strong>{repositories?.find((r) => r.id === run.repository_id)?.name} · {run.source === "ci-agent" && run.check === "unit" ? "unit + lint" : run.check}</strong>
          <span>{STATUSES[run.status] ?? run.status} · {CLEANUP[run.cleanup_status] ?? run.cleanup_status}</span>
          {["queued", "agent", "preparing", "running"].includes(run.status) && <Button variant="secondary" disabled={action.isPending}
            onClick={() => action.mutate({ runId: run.id, action: "stop" }, { onError: toastError("Не удалось остановить прогон") })}>Остановить</Button>}
          {run.cleanup_status === "failed" && <Button variant="secondary" disabled={action.isPending}
            onClick={() => action.mutate({ runId: run.id, action: "cleanup" }, { onError: toastError("Не удалось повторить очистку") })}>Повторить очистку</Button>}
        </div>
        <p className="text-small text-text-3">{new Date(run.created_at).toLocaleString()} · {run.source === "ci-agent" ? "CI-агент" : run.source === "node" ? "Скрипт-нода" : run.source === "manual" ? "Ручной запуск" : "Агент"}
          {run.exit_code !== null && ` · Код завершения ${run.exit_code}`}</p>
        {run.error && <p role="alert">{run.error}</p>}
        {run.cleanup_error && <p role="alert">{run.cleanup_error}</p>}
        <TestRunLogs taskId={taskId} runId={run.id} />
        {run.report_files.length > 0 && <div className="flex flex-wrap gap-3 text-small">
          {run.report_files.map((path) => <a key={path} className="text-accent underline" download
            href={`/api/tasks/${taskId}/artifacts/${path.split("/").map(encodeURIComponent).join("/")}`}>
            {path.split("/").at(-1)}
          </a>)}
        </div>}
      </article>)}
      {runs?.length === 0 && <p>Проверки ещё не запускались.</p>}
    </div>
  </section>;
}

function TestRunLogs({ taskId, runId }: { taskId: string; runId: string }) {
  const [open, setOpen] = useState(false);
  const { data, isLoading, error } = useTestRun(taskId, runId, open);
  return <details onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary className="cursor-pointer">Логи</summary>
    <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all p-2 text-small">
      {error ? "Не удалось загрузить логи" : isLoading ? "Загрузка…" : data?.logs || "Вывод пока отсутствует"}
    </pre>
  </details>;
}
