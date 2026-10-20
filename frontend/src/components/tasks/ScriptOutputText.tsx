import { Fragment } from "react";
import { cn } from "@/lib/utils";
import {
  highlightScriptOutput,
  type LineTone,
  type TokenKind,
} from "@/lib/scriptOutputHighlight";

// Приглушённая палитра из токенов темы (--term-*): мягкая и на светлом, и на тёмном фоне.
const LINE_TONE_CLASS: Record<LineTone, string> = {
  plain: "",
  error: "text-term-error",
  warning: "text-term-warning",
  success: "text-term-success",
};

const TOKEN_CLASS: Record<TokenKind, string> = {
  text: "",
  path: "text-term-path",
  number: "text-term-number",
  string: "text-term-string",
};

/** Раскрашенный вывод script-ноды (раздел 15.2: вывод скрипт-нод визуально отличается). */
export function ScriptOutputText({ text }: { text: string }) {
  const lines = highlightScriptOutput(text);
  return (
    <>
      {lines.map((line, lineIndex) => (
        <Fragment key={lineIndex}>
          <span className={cn(LINE_TONE_CLASS[line.tone], line.tone === "error" && "font-semibold")}>
            {line.tokens.map((token, tokenIndex) => (
              <span
                key={tokenIndex}
                // В строке ошибки цвет задаёт сама строка — подсветка путей и чисел не спорит с ним.
                className={line.tone === "plain" ? TOKEN_CLASS[token.kind] : undefined}
              >
                {token.text}
              </span>
            ))}
          </span>
          {lineIndex < lines.length - 1 && "\n"}
        </Fragment>
      ))}
    </>
  );
}
