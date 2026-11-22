import { ArrowDown } from "lucide-react";
import { Button } from "@/components/ui/button";

/**
 * Лента пролистана вверх: небольшая круглая кнопка у правого нижнего края ленты
 * возвращает к концу. Она плавает поверх ленты и ширину не отнимает: стоит левее полосы
 * прокрутки и над полем ввода, шапку и поле ввода не закрывает, а в самом низу
 * (ближе `JUMP_BUTTON_PX` к концу) скрыта. Точка на ней — ниже появилось новое.
 */
export function ScrollToBottomButton({
  hasUnseen,
  onClick,
}: {
  hasUnseen: boolean;
  onClick: () => void;
}) {
  // Позиционирует обёртка: `touch-hit` у кнопки задаёт `position: relative` и перебил бы `absolute`.
  return (
    <div className="absolute bottom-3 right-5 z-10 short:hidden">
      <Button
        type="button"
        size="icon"
        variant="secondary"
        aria-label={hasUnseen ? "Новые сообщения — перейти в конец" : "Перейти в конец ленты"}
        title={hasUnseen ? "Новые сообщения" : "В конец ленты"}
        className="touch-hit size-8 min-h-0! min-w-0! sm:size-9 rounded-full border border-border bg-surface/90 shadow-md backdrop-blur-sm"
        onClick={onClick}
      >
        <ArrowDown className="size-4" />
        {hasUnseen && (
          <span
            aria-hidden
            data-testid="unseen-dot"
            className="absolute -right-0.5 -top-0.5 size-2.5 rounded-full border-2 border-surface bg-accent"
          />
        )}
      </Button>
    </div>
  );
}
