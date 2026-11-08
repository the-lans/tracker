import { Card } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useLlmAccounts } from "@/hooks/useLlmAccounts";
import { startAccountOptions } from "@/lib/llmAccounts";
import type { Task, TaskUpdateRequest } from "@/lib/types";
import { isPreLaunch } from "@/lib/taskStatusTransitions";

/**
 * Раздел 15.2: стартовый LLM-аккаунт задачи. Меняется до запуска; после
 * запуска — после возврата в статус до запуска, аккаунт работы задачи выбирает воркер.
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
        value={task.llm_account_id ?? ""}
        disabled={!editable || pending}
        onValueChange={(llmAccountId) => onUpdate({ llm_account_id: llmAccountId })}
      >
        <SelectTrigger aria-label="Стартовый LLM-аккаунт" className="mt-2">
          <SelectValue placeholder="Без аккаунта — только скрипты" />
        </SelectTrigger>
        <SelectContent>
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
          ? "С этого аккаунта задача начнёт работу; дальше аккаунт переключается автоматически по порогам из профиля."
          : "Сменить можно, вернув задачу в статус до запуска, — новый прогон начнётся с выбранного аккаунта."}
      </div>
    </Card>
  );
}
