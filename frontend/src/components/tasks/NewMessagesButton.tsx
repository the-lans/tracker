import { ArrowDown } from "lucide-react";
import { Button } from "@/components/ui/button";

/**
 * Лента пролистана вверх, а ниже пришло новое: кнопка у нижнего края ленты
 * возвращает к концу.
 */
export function NewMessagesButton({ onClick }: { onClick: () => void }) {
  return (
    <Button
      type="button"
      size="sm"
      variant="secondary"
      className="absolute bottom-3 left-1/2 z-10 -translate-x-1/2 rounded-full shadow-md short:hidden"
      onClick={onClick}
    >
      <ArrowDown className="size-3.5" />
      Новые сообщения
    </Button>
  );
}
