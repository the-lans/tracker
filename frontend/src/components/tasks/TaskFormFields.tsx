import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { TaskRepositoryPicker } from "@/components/tasks/TaskRepositoryPicker";
import { useLlmAccounts } from "@/hooks/useLlmAccounts";
import { useAuth } from "@/hooks/useAuth";
import type { TaskFormValues } from "@/components/tasks/taskForm.types";
import { EmptyState } from "@/components/common/feedback/EmptyState";
import { AUTO_ACCOUNT, AUTO_ACCOUNT_LABEL, startAccountOptions } from "@/lib/llmAccounts";

const WHITESPACE_RE = /\s/;

/**
 * Поля задачи: код, название, описание, гайд, LLM-аккаунт, репозитории.
 * ``codeError`` — ошибка кода от сервера (код занят или недопустим).
 */
export function TaskFormFields({
  value,
  onChange,
  codeError = null,
}: {
  value: TaskFormValues;
  onChange: (patch: Partial<TaskFormValues>) => void;
  codeError?: string | null;
}) {
  const { user } = useAuth();
  const { data: allLlmAccounts } = useLlmAccounts();
  const options =
    allLlmAccounts && startAccountOptions(allLlmAccounts, user?.id, value.llmAccountId || null);
  const ownAccounts = options?.own;
  const llmAccounts = options?.choices;
  // Раздел 3.1: код задачи — текст без пробелов (из него строится ветка).
  const codeMessage = WHITESPACE_RE.test(value.code)
    ? "Код задачи не должен содержать пробелов"
    : codeError;
  const codeInvalid = codeMessage !== null;

  return (
    <>
      <div>
        <Label htmlFor="task-code">Код задачи</Label>
        <Input
          id="task-code"
          placeholder="RR-10240"
          value={value.code}
          onChange={(event) => onChange({ code: event.target.value })}
          pattern="\S+"
          title="Любой текст без пробелов"
          aria-describedby={codeInvalid ? "task-code-error task-code-hint" : "task-code-hint"}
          aria-invalid={codeInvalid}
          required
        />
        {codeInvalid && (
          <div id="task-code-error" role="alert" className="mt-1 text-meta font-semibold text-danger-text">
            {codeMessage}
          </div>
        )}
        <div id="task-code-hint" className="mt-1 text-meta text-text-3">
          Любой текст без пробелов, например RR-10240 или ключ задачи Jira. Из него же
          строится рабочая ветка feature/&lt;код&gt;.
        </div>
      </div>
      <div>
        <Label htmlFor="task-title">Название</Label>
        <Input
          id="task-title"
          value={value.title}
          onChange={(event) => onChange({ title: event.target.value })}
          required
        />
      </div>
      <div>
        <Label htmlFor="task-description">Описание</Label>
        <Textarea
          id="task-description"
          rows={4}
          value={value.description}
          onChange={(event) => onChange({ description: event.target.value })}
          required
        />
      </div>
      <div>
        <Label htmlFor="task-guide">Гайд (URL Confluence, опционально)</Label>
        <Input
          id="task-guide"
          value={value.guideUrl}
          onChange={(event) => onChange({ guideUrl: event.target.value })}
        />
      </div>
      <div>
        <Label htmlFor="task-llm-account">Стартовый LLM-аккаунт</Label>
        <div className="mb-1 text-meta text-text-3">
          Необязателен: «Автоматически» — аккаунт выберет трекер. LLM нужен нодам с промтами,
          слэш-командами и планированием; задаче из одних скриптов не нужен.
        </div>
        <Select
          value={value.llmAccountId || AUTO_ACCOUNT}
          onValueChange={(choice) => onChange({ llmAccountId: choice === AUTO_ACCOUNT ? "" : choice })}
        >
          <SelectTrigger id="task-llm-account">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={AUTO_ACCOUNT}>{AUTO_ACCOUNT_LABEL}</SelectItem>
            {(llmAccounts ?? []).map((account) => (
              <SelectItem key={account.id} value={account.id}>
                {account.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {ownAccounts && ownAccounts.length === 0 && (
          <EmptyState
            compact
            title="LLM-аккаунтов пока нет"
            hint="Без аккаунта можно запускать только скрипты. Добавьте свой аккаунт в разделе «LLM-аккаунты» кнопкой «+ Аккаунт»."
          />
        )}
        {ownAccounts && ownAccounts.length > 0 && llmAccounts?.length === 0 && (
          <div className="mt-1 text-meta text-warning-text">
            Нет активных аккаунтов: войдите в аккаунт или включите его в разделе «LLM-аккаунты».
          </div>
        )}
        <div className="mt-1 text-meta text-text-3">
          С выбранного аккаунта задача начнёт работу, если его окно лимита свободно или запущено;
          дальше аккаунт выбирается автоматически.
        </div>
      </div>
      <div>
        <Label>Репозитории</Label>
        <TaskRepositoryPicker
          value={value.repositories}
          onChange={(repositories) => onChange({ repositories })}
        />
      </div>
    </>
  );
}
