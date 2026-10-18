import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useCreateTask } from "@/hooks/useTasks";
import { ApiError } from "@/lib/apiClient";

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

  function reset() {
    setCode("");
    setTitle("");
    setDescription("");
    setGuideUrl("");
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    createTask.mutate(
      { code, title, description, guide_url: guideUrl || null },
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
