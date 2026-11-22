import { useCallback, useEffect, useRef, useState } from "react";

/** Расстояние до конца ленты, в пределах которого она следует за новым содержимым. */
export const NEAR_BOTTOM_PX = 120;
/** Дальше этого расстояния от конца появляется кнопка «вниз». */
export const JUMP_BUTTON_PX = 200;

function distanceToBottom(feed: HTMLElement): number {
  return feed.scrollHeight - feed.scrollTop - feed.clientHeight;
}

/**
 * Лента, которая прокручивается вместе с новым содержимым (растущий ответ, новые
 * реплики), пока пользователь у её конца. Пролистал выше — лента стоит на месте, а
 * ``hasUnseen`` подсказывает, что ниже появилось новое, ``awayFromBottom`` — что лента
 * пролистана вверх настолько, что нужна кнопка «вниз»; ``scrollToBottom`` возвращает
 * к концу. ``contentSignal`` меняется, когда содержимое выросло.
 */
export function useStickToBottom<T extends HTMLElement>(
  contentSignal: unknown,
) {
  const ref = useRef<T>(null);
  // Начало работы с лентой — у конца: история открывается снизу.
  const stuck = useRef(true);
  const [hasUnseen, setHasUnseen] = useState(false);
  const [awayFromBottom, setAwayFromBottom] = useState(false);

  const onScroll = useCallback(() => {
    const feed = ref.current;
    if (feed === null) return;
    const distance = distanceToBottom(feed);
    stuck.current = distance <= NEAR_BOTTOM_PX;
    setAwayFromBottom(distance > JUMP_BUTTON_PX);
    if (stuck.current) setHasUnseen(false);
  }, []);

  const scrollToBottom = useCallback(() => {
    const feed = ref.current;
    if (feed === null) return;
    stuck.current = true;
    setHasUnseen(false);
    setAwayFromBottom(false);
    feed.scrollTo({ top: feed.scrollHeight });
  }, []);

  useEffect(() => {
    const feed = ref.current;
    if (feed === null) return;
    // Без плавной прокрутки: она шлёт события прокрутки на полпути и «открепила» бы ленту.
    if (stuck.current) {
      feed.scrollTo({ top: feed.scrollHeight });
      setAwayFromBottom(false);
    } else {
      // Не у конца: новое содержимое ниже видимой части, о нём напоминает кнопка.
      setHasUnseen(true);
      setAwayFromBottom(distanceToBottom(feed) > JUMP_BUTTON_PX);
    }
  }, [contentSignal]);

  return { ref, onScroll, hasUnseen, awayFromBottom, scrollToBottom };
}
