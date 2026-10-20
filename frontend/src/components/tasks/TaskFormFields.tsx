import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { TaskRepositoryPicker } from "@/components/tasks/TaskRepositoryPicker";
import { useLlmAccounts } from "@/hooks/useLlmAccounts";
import type { TaskFormValues } from "@/components/tasks/taskForm.types";

/** Поля задачи: код, название, описание, гайд, LLM-аккаунт, репозитории. */
export function TaskFormFields({
  value,
  onChange,
}: {
  value: TaskFormValues;
  onChange: (patch: Partial<TaskFormValues>) => void;
}) {
  const { data: llmAccounts } = useLlmAccounts();

  return (
    <>
      <div>
        <Label htmlFor="task-code">Код задачи</Label>
        <Input
          id="task-code"
          placeholder="RR-10240"
          value={value.code}
          onChange={(event) => onChange({ code: event.target.value })}
          required
        />
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
        <Label>LLM-аккаунт</Label>
        <Select value={value.llmAccountId} onValueChange={(llmAccountId) => onChange({ llmAccountId })}>
          <SelectTrigger>
            <SelectValue placeholder="Выберите аккаунт" />
          </SelectTrigger>
          <SelectContent>
            {(llmAccounts ?? []).map((account) => (
              <SelectItem key={account.id} value={account.id}>
                {account.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
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
