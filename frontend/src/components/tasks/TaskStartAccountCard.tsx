import { Card } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useLlmAccounts } from "@/hooks/useLlmAccounts";
import { AUTO_ACCOUNT, AUTO_ACCOUNT_LABEL, startAccountOptions } from "@/lib/llmAccounts";
import type { Task, TaskUpdateRequest } from "@/lib/types";
import { isPreLaunch } from "@/lib/taskStatusTransitions";

/**
 * Раздел 15.2: стартовый LLM-аккаунт задачи, необязательный — «Автоматически»
 * оставляет выбор трекеру (раздел 19.7). Меняется до запуска; после запуска —
 * после возврата в статус до запуска, аккаунт работы задачи выбирает воркер.
 */
export function TaskStartAccountCard({
  task,
  pending,
  onUpdate,
}: {
  task: Task;
  pending: boolean;
  onUpdate: (body: TaskUpdateRequest) => void;
}) {
  const { data: accounts } = useLlmAccounts();
  const options = accounts && startAccountOptions(accounts, task.created_by, task.llm_account_id);
  const editable = isPreLaunch(task.status);

  return (
    <Card>
      <div className="text-body font-bold">Стартовый LLM-аккаунт</div>
      <Select
        value={task.llm_account_id ?? AUTO_ACCOUNT}
        disabled={!editable || pending}
        onValueChange={(choice) =>
          onUpdate({ llm_account_id: choice === AUTO_ACCOUNT ? null : choice })
        }
      >
        <SelectTrigger aria-label="Стартовый LLM-аккаунт" className="mt-2">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={AUTO_ACCOUNT}>{AUTO_ACCOUNT_LABEL}</SelectItem>
          {(options?.choices ?? []).map((account) => (
            <SelectItem key={account.id} value={account.id}>
              {account.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {options && options.own.length > 0 && options.choices.length === 0 && (
        <div className="mt-1 text-meta text-warning-text">
          Нет активных аккаунтов: войдите в аккаунт или включите его в разделе «LLM-аккаунты».
        </div>
      )}
      <div className="mt-1 text-meta text-text-3">
        {editable
          ? "С выбранного аккаунта задача начнёт работу, если его окно лимита свободно или запущено; «Автоматически» — аккаунт выберет трекер."
          : "Сменить можно, вернув задачу в статус до запуска, — новый прогон начнётся с выбранного аккаунта."}
      </div>
    </Card>
  );
}
