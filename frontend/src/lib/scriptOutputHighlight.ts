/**
 * Раскраска вывода script-ноды: строка целиком получает тон по смыслу
 * (ошибка, предупреждение, успех), внутри обычных строк подсвечиваются
 * пути, числа и строки в кавычках.
 */

export type LineTone = "plain" | "error" | "warning" | "success";
export type TokenKind = "text" | "path" | "number" | "string";

export interface OutputToken {
  kind: TokenKind;
  text: string;
}

export interface OutputLine {
  tone: LineTone;
  tokens: OutputToken[];
}

const ERROR_LINE =
  /\b(traceback|errors?|exception|failed|failures?|fatal|panic)\b|^\s*(E\s|!\s)|\b\w+Error\b/i;
const WARNING_LINE = /\b(warn|warnings?|deprecated)\b|\b\w+Warning\b/i;
// Итоги вида «5 passed, 0 failed», «Found 0 errors» или «No errors found» — не ошибка.
const ZERO_COUNT = /\b(0|no)\s+(errors?|failed|failures?|warnings?)\b/gi;
const SUCCESS_LINE = /(\b(ok|passed|success|succeeded|done)\b|✓|✔)/i;

// Путь: есть «/» или имя файла с расширением; строка в кавычках; число.
const TOKEN_RE =
  /("[^"\n]*"|'[^'\n]*')|((?:\.{0,2}\/)?[\w.-]+(?:\/[\w.-]+)+\/?|\b[\w-]+\.(?:py|sh|ts|tsx|js|json|md|txt|csv|yml|yaml|toml|cfg|log)\b)|(\b\d+(?:\.\d+)?%?)/g;

function lineTone(line: string): LineTone {
  const meaningful = line.replace(ZERO_COUNT, "");
  if (ERROR_LINE.test(meaningful)) return "error";
  if (WARNING_LINE.test(meaningful)) return "warning";
  if (SUCCESS_LINE.test(meaningful)) return "success";
  return "plain";
}

function tokenize(line: string): OutputToken[] {
  const tokens: OutputToken[] = [];
  let last = 0;
  for (const match of line.matchAll(TOKEN_RE)) {
    const index = match.index ?? 0;
    if (index > last) tokens.push({ kind: "text", text: line.slice(last, index) });
    const kind: TokenKind = match[1] ? "string" : match[2] ? "path" : "number";
    tokens.push({ kind, text: match[0] });
    last = index + match[0].length;
  }
  if (last < line.length) tokens.push({ kind: "text", text: line.slice(last) });
  return tokens;
}

export function highlightScriptOutput(text: string): OutputLine[] {
  return text.split("\n").map((line) => ({ tone: lineTone(line), tokens: tokenize(line) }));
}
