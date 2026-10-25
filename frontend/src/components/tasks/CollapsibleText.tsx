import { useState, type ReactNode } from "react";
import { Copy, Download } from "lucide-react";
import { copyText, downloadText } from "@/lib/textExport";

const PREVIEW_LENGTH = 320;

/** Раздел 15.2: "каждый блок вывода по умолчанию свёрнут до короткого
 * превью... не должен автоматически растягивать страницу", плюс
 * копирование/скачивание полного текста. */
export function CollapsibleText({
  text,
  filename,
  className,
  monospace,
  live = false,
  renderText,
}: {
  text: string;
  filename?: string;
  className?: string;
  monospace?: boolean;
  /** Текст ещё генерируется — показывается целиком, по мере поступления (раздел 15.2). */
  live?: boolean;
  /** Своё оформление видимой части текста (например, раскраска вывода скрипта). */
  renderText?: (text: string) => ReactNode;
}) {
  // `null` — пользователь не разворачивал: текст, выросший после показа
  // (например, вывод скрипта вместо «(пусто)»), тоже остаётся свёрнутым.
  const [userExpanded, setUserExpanded] = useState<boolean | null>(null);
  const isTruncatable = text.length > PREVIEW_LENGTH;
  const expanded = !isTruncatable || (userExpanded ?? live);
  const shown = expanded ? text : `${text.slice(0, PREVIEW_LENGTH)}…`;

  return (
    <div className={className}>
      <div
        className={
          monospace
            ? "whitespace-pre-wrap font-mono text-small leading-relaxed [overflow-wrap:anywhere]"
            : "whitespace-pre-wrap [overflow-wrap:anywhere]"
        }
      >
        {renderText ? renderText(shown) : shown}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
        {isTruncatable && (
          <button
            type="button"
            onClick={() => setUserExpanded(!expanded)}
            className="touch-hit whitespace-nowrap text-meta font-bold text-accent"
          >
            {expanded ? "Свернуть" : "Показать полностью →"}
          </button>
        )}
        <button
          type="button"
          onClick={() => copyText(text)}
          className="touch-hit inline-flex items-center gap-1 text-caption font-semibold text-text-3 hover:text-text-2"
        >
          <Copy className="size-3" /> Копировать
        </button>
        <button
          type="button"
          onClick={() => downloadText(text, filename ?? "output.txt")}
          className="touch-hit inline-flex items-center gap-1 text-caption font-semibold text-text-3 hover:text-text-2"
        >
          <Download className="size-3" /> Скачать
        </button>
      </div>
    </div>
  );
}
