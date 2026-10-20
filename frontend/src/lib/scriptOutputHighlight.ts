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
  /\b(traceback|error|exception|failed|failure|fatal|panic)\b|^\s*(E\s|!\s)|\b\w+Error\b/i;
const WARNING_LINE = /\b(warn|warning|deprecated)\b/i;
const SUCCESS_LINE = /(\b(ok|passed|success|succeeded|done)\b|✓|✔)/i;

// Путь: есть «/» или имя файла с расширением; строка в кавычках; число.
const TOKEN_RE =
  /("[^"\n]*"|'[^'\n]*')|((?:\.{0,2}\/)?[\w.-]+(?:\/[\w.-]+)+\/?|\b[\w-]+\.(?:py|sh|ts|tsx|js|json|md|txt|csv|yml|yaml|toml|cfg|log)\b)|(\b\d+(?:\.\d+)?%?)/g;

function lineTone(line: string): LineTone {
  if (ERROR_LINE.test(line)) return "error";
  if (WARNING_LINE.test(line)) return "warning";
  if (SUCCESS_LINE.test(line)) return "success";
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
