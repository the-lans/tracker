import { RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { useRefreshJiraDescription } from "@/hooks/useTasks";
import { errorMessage } from "@/lib/errors";

/** Раздел 15.6: подгружает отрисованное описание из Jira у задачи, импортированной раньше. */
export function RefreshJiraDescriptionButton({ taskId }: { taskId: string }) {
  const refresh = useRefreshJiraDescription(taskId);
  return (
    <Button
      variant="ghost"
      size="sm"
      disabled={refresh.isPending}
      onClick={() =>
        refresh.mutate(undefined, {
          onSuccess: () => toast.success("Описание обновлено из Jira"),
          onError: (error) => toast.error(errorMessage(error, "Не удалось обновить описание из Jira")),
        })
      }
    >
      <RefreshCw className="size-3" />
      Обновить из Jira
    </Button>
  );
}
