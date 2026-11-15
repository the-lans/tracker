import { useState } from "react";
import { Archive } from "lucide-react";
import { toast } from "sonner";
import { ButtonLabel } from "@/components/common/actions/ButtonLabel";
import { ConfirmDialog } from "@/components/common/dialogs/ConfirmDialog";
import { useChangeTaskStatus } from "@/hooks/useTasks";
import { toastError } from "@/lib/errors";
import { TaskStatus, type Task } from "@/lib/types";
import { HEADER_BUTTON } from "@/styles/classes";

export function TaskArchiveButton({ task, compact = false }: { task: Task; compact?: boolean }) {
  const [open, setOpen] = useState(false);
  const changeStatus = useChangeTaskStatus(task.id);

  if (task.status !== TaskStatus.DONE && task.status !== TaskStatus.FAILED) return null;

  function archive() {
    changeStatus.mutate(TaskStatus.ARCHIVED, {
      onSuccess: () => {
        setOpen(false);
        toast.success("Задача перенесена в архив");
      },
      onError: toastError("Не удалось архивировать задачу"),
    });
  }

  return (
    <>
      <button
        type="button"
        className={compact ? "ml-auto flex touch-target size-[30px] items-center justify-center rounded-[9px] border border-border text-text-2" : HEADER_BUTTON}
        aria-label="Архивировать задачу"
        title="Архивировать задачу"
        disabled={changeStatus.isPending}
        onClick={() => setOpen(true)}
      >
        <Archive className="size-3.5" />
        {!compact && <ButtonLabel>В архив</ButtonLabel>}
      </button>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title="Перенести задачу в архив?"
        description="Задача исчезнет с дашборда и останется доступна в разделе «Архив»."
        confirmLabel="В архив"
        pending={changeStatus.isPending}
        onConfirm={archive}
      />
    </>
  );
}
