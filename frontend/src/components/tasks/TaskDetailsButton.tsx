import { useState } from "react";
import { Maximize2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { TaskDetailsDialog } from "@/components/tasks/TaskDetailsDialog";
import type { Task } from "@/lib/types";

/** Рядом с заголовком «Обзор»: открывает описание, ссылки и артефакты в отдельном окне. */
export function TaskDetailsButton({ task }: { task: Task }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        // Компактная рядом с заголовком «Обзор»; зона нажатия — `touch-hit`.
        className="touch-hit h-7 min-h-0! px-2"
        aria-label="Открыть название, описание, ссылки и артефакты в отдельном окне"
        onClick={() => setOpen(true)}
      >
        <Maximize2 className="size-3" />В отдельном окне
      </Button>
      <TaskDetailsDialog task={task} open={open} onOpenChange={setOpen} />
    </>
  );
}
