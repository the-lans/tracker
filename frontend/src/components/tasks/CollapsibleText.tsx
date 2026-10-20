import { useState } from "react";
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
}: {
  text: string;
  filename?: string;
  className?: string;
  monospace?: boolean;
}) {
  const [expanded, setExpanded] = useState(text.length <= PREVIEW_LENGTH);
  const isTruncatable = text.length > PREVIEW_LENGTH;
  const shown = expanded ? text : `${text.slice(0, PREVIEW_LENGTH)}…`;

  return (
    <div className={className}>
      <div className={monospace ? "whitespace-pre-wrap font-mono text-[12px] leading-relaxed" : "whitespace-pre-wrap"}>
        {shown}
      </div>
      <div className="mt-2 flex items-center gap-3">
        {isTruncatable && (
          <button
            type="button"
            onClick={() => setExpanded((prev) => !prev)}
            className="text-[11.5px] font-bold text-accent"
          >
            {expanded ? "Свернуть" : "Показать полностью →"}
          </button>
        )}
        <button
          type="button"
          onClick={() => copyText(text)}
          className="inline-flex items-center gap-1 text-[11px] font-semibold text-text-3 hover:text-text-2"
        >
          <Copy className="size-3" /> Копировать
        </button>
        <button
          type="button"
          onClick={() => downloadText(text, filename ?? "output.txt")}
          className="inline-flex items-center gap-1 text-[11px] font-semibold text-text-3 hover:text-text-2"
        >
          <Download className="size-3" /> Скачать
        </button>
      </div>
    </div>
  );
}
