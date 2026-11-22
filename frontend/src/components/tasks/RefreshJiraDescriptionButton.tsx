import { RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { useRefreshJiraDescription } from "@/hooks/useTasks";
import { errorMessage } from "@/lib/errors";

/** Раздел 15.6: заменяет описание задачи текущим описанием из Jira (правки в трекере теряются). */
export function RefreshJiraDescriptionButton({ taskId }: { taskId: string }) {
  const refresh = useRefreshJiraDescription(taskId);
  return (
    <Button
      variant="ghost"
      size="sm"
      title="Заменить описание текущим из Jira: правки, сделанные в трекере, будут потеряны"
      disabled={refresh.isPending}
      onClick={() =>
        refresh.mutate(undefined, {
          onSuccess: () => toast.success("Описание обновлено из Jira"),
          onError: (error) =>
            toast.error(
              errorMessage(error, "Не удалось обновить описание из Jira"),
            ),
        })
      }
    >
      <RefreshCw className="size-3" />
      Обновить из Jira
    </Button>
  );
}
