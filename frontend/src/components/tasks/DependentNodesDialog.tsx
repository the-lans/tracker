import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import type { PendingNodeDisable } from "@/hooks/useDependentNodesGuard";

/** Раздел 13.3, 15.2: предупреждение с указанием конкретных зависимых нод. */
export function DependentNodesDialog({
  pending,
  onConfirm,
  onCancel,
}: {
  pending: PendingNodeDisable | null;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <ConfirmDialog
      open={pending !== null}
      onOpenChange={(open) => !open && onCancel()}
      title="Отключить ноду?"
      confirmLabel="Всё равно отключить"
      danger
      onConfirm={onConfirm}
      description={
        pending && (
          <>
            На вывод ноды «{pending.nodeName}» ссылаются последующие ноды — без неё они получат
            вывод другой ноды или пустое значение:
            <ul className="mt-2 list-disc pl-5">
              {pending.dependents.map((dependent) => (
                <li key={dependent.node_id}>{dependent.name}</li>
              ))}
            </ul>
          </>
        )
      }
    />
  );
}
