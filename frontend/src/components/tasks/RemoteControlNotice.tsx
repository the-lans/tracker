/**
 * Раздел 6.3: рядом с кнопкой переподключения — видимая, а не только во
 * всплывающей подсказке (её нет на сенсорных экранах), пометка, что в
 * `claude.ai/code` сессия только для просмотра.
 */
export function RemoteControlNotice() {
  return (
    <p className="basis-full text-right text-caption text-text-3">
      В claude.ai/code сессия доступна только для просмотра — отвечать агенту можно через поля
      трекера
    </p>
  );
}
