import { useState, type FormEvent } from "react";
import { Pencil } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useUpdatePipeline } from "@/hooks/usePipelines";
import { toastError } from "@/lib/errors";
import type { Pipeline } from "@/lib/types";

/** Иконка-карандаш и диалог «Переименовать пайплайн»; нужна и в списке, и на странице пайплайна. */
export function RenamePipelineButton({ pipeline }: { pipeline: Pipeline }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(pipeline.name);
  const updatePipeline = useUpdatePipeline(pipeline.id);
  const trimmed = name.trim();
  const canSave = trimmed !== "" && trimmed !== pipeline.name && !updatePipeline.isPending;

  function handleOpenChange(next: boolean) {
    // Каждый раз начинаем с актуального названия, а не с недописанной правки.
    if (next) setName(pipeline.name);
    setOpen(next);
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!canSave) return;
    updatePipeline.mutate(
      { name: trimmed },
      {
        onSuccess: () => {
          toast.success("Пайплайн переименован");
          setOpen(false);
        },
        onError: toastError("Не удалось переименовать пайплайн"),
      },
    );
  }

  return (
    <>
      <button
        type="button"
        onClick={() => handleOpenChange(true)}
        className="touch-target flex shrink-0 items-center justify-center text-text-3 hover:text-text"
        aria-label={`Переименовать ${pipeline.name}`}
        title="Переименовать"
      >
        <Pencil className="size-4" />
      </button>
      <Dialog open={open} onOpenChange={handleOpenChange}>
        <DialogContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <DialogHeader>
              <DialogTitle>Переименовать пайплайн</DialogTitle>
            </DialogHeader>
            <div>
              <Label htmlFor="pipeline-rename" required>Название</Label>
              <Input
                id="pipeline-rename"
                value={name}
                onChange={(event) => setName(event.target.value)}
                autoFocus
              />
            </div>
            <DialogFooter>
              <Button type="button" variant="secondary" onClick={() => setOpen(false)}>
                Отмена
              </Button>
              <Button type="submit" disabled={!canSave}>
                Сохранить
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
