import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { TaskRepositoryPicker } from "@/components/tasks/TaskRepositoryPicker";
import { useLlmAccounts } from "@/hooks/useLlmAccounts";
import { useCreateTask } from "@/hooks/useTasks";
import { ApiError } from "@/lib/apiClient";
import type { TaskRepositoryAttach } from "@/lib/types";

export function CreateTaskDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const navigate = useNavigate();
  const createTask = useCreateTask();
  const [code, setCode] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [guideUrl, setGuideUrl] = useState("");
  const [llmAccountId, setLlmAccountId] = useState("");
  const [repositories, setRepositories] = useState<TaskRepositoryAttach[]>([]);
  const { data: llmAccounts } = useLlmAccounts();

  function reset() {
    setCode("");
    setTitle("");
    setDescription("");
    setGuideUrl("");
    setLlmAccountId("");
    setRepositories([]);
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    createTask.mutate(
      {
        code,
        title,
        description,
        guide_url: guideUrl || null,
        llm_account_id: llmAccountId || null,
        repositories,
      },
      {
        onSuccess: (task) => {
          reset();
          onOpenChange(false);
          navigate(`/tasks/${task.id}`);
        },
        onError: (error) => {
          toast.error(error instanceof ApiError ? error.message : "Не удалось создать задачу");
        },
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Новая задача</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <div>
            <Label htmlFor="task-code">Код задачи</Label>
            <Input
              id="task-code"
              placeholder="RR-10240"
              value={code}
              onChange={(event) => setCode(event.target.value)}
              required
            />
          </div>
          <div>
            <Label htmlFor="task-title">Название</Label>
            <Input
              id="task-title"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              required
            />
          </div>
          <div>
            <Label htmlFor="task-description">Описание</Label>
            <Textarea
              id="task-description"
              rows={4}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              required
            />
          </div>
          <div>
            <Label htmlFor="task-guide">Гайд (URL Confluence, опционально)</Label>
            <Input
              id="task-guide"
              value={guideUrl}
              onChange={(event) => setGuideUrl(event.target.value)}
            />
          </div>
          <div>
            <Label>LLM-аккаунт</Label>
            <Select value={llmAccountId} onValueChange={setLlmAccountId}>
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
            <TaskRepositoryPicker value={repositories} onChange={setRepositories} />
          </div>
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={() => onOpenChange(false)}>
              Отмена
            </Button>
            <Button type="submit" disabled={createTask.isPending}>
              Создать
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
