/**
 * Небольшой разбор markdown-ответа агента для ленты: только то, что агент
 * реально присылает (заголовки, списки, таблицы, жирный, код). Результат — дерево
 * данных, отрисовка идёт React-элементами, поэтому HTML из ответа не
 * исполняется.
 */

export type InlineKind = "text" | "bold" | "code";

export interface InlinePart {
  kind: InlineKind;
  text: string;
  /** Код внутри жирного текста (`**\`calc.py\`**`). */
  bold?: boolean;
}

export type TableAlign = "left" | "center" | "right";

export type MarkdownBlock =
  | { kind: "heading"; level: number; parts: InlinePart[] }
  | { kind: "paragraph"; parts: InlinePart[] }
  | { kind: "list"; ordered: boolean; items: InlinePart[][] }
  | { kind: "code"; language: string; code: string }
  | { kind: "table"; align: TableAlign[]; header: InlinePart[][]; rows: InlinePart[][][] };

export type CodeTokenKind = "text" | "keyword" | "string" | "number" | "comment";

export interface CodeToken {
  kind: CodeTokenKind;
  text: string;
}

const HEADING_RE = /^(#{1,4})\s+(.*)$/;
const BULLET_RE = /^\s*[-*•]\s+(.*)$/;
const ORDERED_RE = /^\s*\d+[.)]\s+(.*)$/;
const FENCE_RE = /^\s*```\s*([\w+-]*)\s*$/;
const INLINE_RE = /(\*\*[^*\n]+\*\*)|(`[^`\n]+`)/g;
const CODE_SPAN_RE = /`[^`\n]+`/g;
// Разделитель шапки таблицы: `---`, `:---`, `:---:`, `---:` в каждой ячейке.
const TABLE_SEPARATOR_CELL_RE = /^:?-+:?$/;
const TABLE_CELL_SPLIT_RE = /(?<!\\)\|/;

/** Части жирного текста: код внутри остаётся кодом, но тоже жирным. */
function boldParts(text: string): InlinePart[] {
  const parts: InlinePart[] = [];
  let last = 0;
  for (const match of text.matchAll(CODE_SPAN_RE)) {
    const index = match.index ?? 0;
    if (index > last) parts.push({ kind: "bold", text: text.slice(last, index) });
    parts.push({ kind: "code", text: match[0].slice(1, -1), bold: true });
    last = index + match[0].length;
  }
  if (last < text.length) parts.push({ kind: "bold", text: text.slice(last) });
  return parts;
}

export function parseInline(text: string): InlinePart[] {
  const parts: InlinePart[] = [];
  let last = 0;
  for (const match of text.matchAll(INLINE_RE)) {
    const index = match.index ?? 0;
    if (index > last) parts.push({ kind: "text", text: text.slice(last, index) });
    if (match[1]) parts.push(...boldParts(match[1].slice(2, -2)));
    else parts.push({ kind: "code", text: match[0].slice(1, -1) });
    last = index + match[0].length;
  }
  if (last < text.length) parts.push({ kind: "text", text: text.slice(last) });
  return parts;
}

/** Ячейки строки таблицы; крайние `|` необязательны, `\|` — символ, а не граница. */
function splitTableRow(line: string): string[] {
  let row = line.trim();
  if (row.startsWith("|")) row = row.slice(1);
  if (row.endsWith("|") && !row.endsWith("\\|")) row = row.slice(0, -1);
  return row.split(TABLE_CELL_SPLIT_RE).map((cell) => cell.trim().replaceAll("\\|", "|"));
}

function tableAlign(cells: string[]): TableAlign[] | null {
  if (!cells.every((cell) => TABLE_SEPARATOR_CELL_RE.test(cell))) return null;
  return cells.map((cell) => {
    if (cell.startsWith(":") && cell.endsWith(":")) return "center";
    return cell.endsWith(":") ? "right" : "left";
  });
}

/** Таблица с шапкой в строке `index`; `null`, если это не таблица. */
function parseTable(lines: string[], index: number): { block: MarkdownBlock; next: number } | null {
  if (!lines[index].includes("|") || index + 1 >= lines.length) return null;
  const header = splitTableRow(lines[index]);
  const align = tableAlign(splitTableRow(lines[index + 1]));
  if (!align || align.length !== header.length) return null;
  const rows: InlinePart[][][] = [];
  let next = index + 2;
  while (next < lines.length && lines[next].includes("|") && lines[next].trim()) {
    const cells = splitTableRow(lines[next]);
    rows.push(header.map((_, column) => parseInline(cells[column] ?? "")));
    next += 1;
  }
  return { block: { kind: "table", align, header: header.map((cell) => parseInline(cell)), rows }, next };
}

export function parseMarkdown(text: string): MarkdownBlock[] {
  const blocks: MarkdownBlock[] = [];
  const lines = text.split("\n");
  let paragraph: string[] = [];

  const flushParagraph = () => {
    if (paragraph.length) blocks.push({ kind: "paragraph", parts: parseInline(paragraph.join("\n")) });
    paragraph = [];
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const fence = line.match(FENCE_RE);
    if (fence) {
      flushParagraph();
      const code: string[] = [];
      i += 1;
      // Незакрытый блок (обрезанное превью, поток) тоже показываем как код.
      while (i < lines.length && !FENCE_RE.test(lines[i])) code.push(lines[i++]);
      blocks.push({ kind: "code", language: fence[1].toLowerCase(), code: code.join("\n") });
      continue;
    }
    const heading = line.match(HEADING_RE);
    if (heading) {
      flushParagraph();
      blocks.push({ kind: "heading", level: heading[1].length, parts: parseInline(heading[2]) });
      continue;
    }
    const bullet = line.match(BULLET_RE);
    const ordered = bullet ? null : line.match(ORDERED_RE);
    if (bullet || ordered) {
      flushParagraph();
      const isOrdered = Boolean(ordered);
      const item = parseInline((bullet ?? ordered)![1]);
      const previous = blocks[blocks.length - 1];
      if (previous?.kind === "list" && previous.ordered === isOrdered) previous.items.push(item);
      else blocks.push({ kind: "list", ordered: isOrdered, items: [item] });
      continue;
    }
    const table = parseTable(lines, i);
    if (table) {
      flushParagraph();
      blocks.push(table.block);
      i = table.next - 1;
      continue;
    }
    if (!line.trim()) {
      flushParagraph();
      continue;
    }
    paragraph.push(line);
  }
  flushParagraph();
  return blocks;
}

const KEYWORDS = new Set(
  (
    "def class return if elif else for while in not and or import from as with try except finally raise " +
    "lambda yield async await None True False pass break continue const let var function new export " +
    "interface type extends implements null undefined true false this public private static echo fi then do done"
  ).split(" "),
);

const CODE_RE = /(#[^\n]*|\/\/[^\n]*)|("(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'|`[^`\n]*`)|(\b\d+(?:\.\d+)?\b)|([A-Za-z_]\w*)/g;

export function highlightCode(code: string): CodeToken[] {
  const tokens: CodeToken[] = [];
  let last = 0;
  for (const match of code.matchAll(CODE_RE)) {
    const index = match.index ?? 0;
    let kind: CodeTokenKind | null = null;
    if (match[1]) kind = "comment";
    else if (match[2]) kind = "string";
    else if (match[3]) kind = "number";
    else if (match[4] && KEYWORDS.has(match[4])) kind = "keyword";
    if (!kind) continue;
    if (index > last) tokens.push({ kind: "text", text: code.slice(last, index) });
    tokens.push({ kind, text: match[0] });
    last = index + match[0].length;
  }
  if (last < code.length) tokens.push({ kind: "text", text: code.slice(last) });
  return tokens;
}
