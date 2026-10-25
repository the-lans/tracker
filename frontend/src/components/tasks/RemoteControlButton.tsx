import { RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { useReconnectRemoteControl } from "@/hooks/useTasks";
import { errorMessage } from "@/lib/errors";
import { RemoteControlStatus, type Task } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ButtonLabel } from "@/components/common/actions/ButtonLabel";

/** Раздел 6.5: «Переподключить удалённую сессию» — доступна всегда
 * (блокируется только на время самого запроса), акцент при разрыве. */
export function RemoteControlButton({ task }: { task: Task }) {
  const reconnect = useReconnectRemoteControl(task.id);
  const disconnected = task.remote_control_status === RemoteControlStatus.DISCONNECTED;
  const reconnecting = task.remote_control_status === RemoteControlStatus.RECONNECTING;

  function handleClick() {
    reconnect.mutate(undefined, {
      onSuccess: () => toast.success("Мост переподключится перед следующим обращением к сессии"),
      onError: (error) => {
        toast.error(errorMessage(error, "Не удалось переподключить сессию"));
      },
    });
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={reconnect.isPending}
      aria-label="Переподключить удалённую сессию"
      // Раздел 15.2: кнопка присутствует всегда; на телефоне — только значок.
      className={cn(
        "flex touch-target items-center justify-center gap-2 whitespace-nowrap rounded-md border px-3 py-2 text-body font-bold disabled:opacity-60 short:py-1",
        disconnected
          ? "border-warning-border bg-warning-tint text-warning-text"
          : "border-border bg-surface text-text-2",
      )}
    >
      <RefreshCw className={cn("size-3.5", reconnecting && "animate-spin")} />
      <ButtonLabel>
        {reconnecting ? "Переподключение…" : "Переподключить удалённую сессию"}
      </ButtonLabel>
    </button>
  );
}
