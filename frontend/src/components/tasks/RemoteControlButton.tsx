import { RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { useReconnectRemoteControl } from "@/hooks/useTasks";
import { ApiError } from "@/lib/apiClient";
import { RemoteControlStatus, type Task } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Раздел 6.3, 6.5: «Переподключить удалённую сессию» — доступна всегда,
 * акцент при разрыве. В `claude.ai/code` сессия только для просмотра:
 * вмешиваться в работу агента — через поля трекера. */
export function RemoteControlButton({ task }: { task: Task }) {
  const reconnect = useReconnectRemoteControl(task.id);
  const disconnected = task.remote_control_status === RemoteControlStatus.DISCONNECTED;
  const reconnecting = task.remote_control_status === RemoteControlStatus.RECONNECTING;

  function handleClick() {
    reconnect.mutate(undefined, {
      onSuccess: () => toast.success("Мост переподключится перед следующим обращением к сессии"),
      onError: (error) => {
        toast.error(error instanceof ApiError ? error.message : "Не удалось переподключить сессию");
      },
    });
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={reconnect.isPending || reconnecting}
      title="В claude.ai/code сессия доступна для просмотра; отвечать агенту — через поля трекера"
      className={cn(
        "hidden items-center gap-2 rounded-md border px-3 py-2 text-[13px] font-bold disabled:opacity-60 sm:flex",
        disconnected
          ? "border-warning-border bg-warning-tint text-warning-text"
          : "border-border bg-surface text-text-2",
      )}
    >
      <RefreshCw className={cn("size-3.5", reconnecting && "animate-spin")} />
      {reconnecting ? "Переподключение…" : "Переподключить сессию"}
    </button>
  );
}
