/**
 * Небольшой разбор markdown-ответа агента для ленты: только то, что агент
 * реально присылает (заголовки, списки, таблицы, жирный, код). Результат — дерево
 * данных, отрисовка идёт React-элементами, поэтому HTML из ответа не
 * исполняется.
 */

export type InlineKind = "text" | "bold" | "code" | "link";

export interface InlinePart {
  kind: InlineKind;
  text: string;
  /** Код внутри жирного текста (`**\`calc.py\`**`). */
  bold?: boolean;
  href?: string;
}

export type TableAlign = "left" | "center" | "right";

export type MarkdownBlock =
  | { kind: "heading"; level: number; parts: InlinePart[] }
  | { kind: "paragraph"; parts: InlinePart[] }
  // `start` — номер первого пункта нумерованного списка: список, разорванный блоком
  // кода или вложенным списком, продолжает нумерацию, а не начинает с «1.».
  | { kind: "list"; ordered: boolean; items: InlinePart[][]; start: number }
  | { kind: "code"; language: string; code: string }
  | { kind: "table"; align: TableAlign[]; header: InlinePart[][]; rows: InlinePart[][][] };

export type CodeTokenKind = "text" | "keyword" | "string" | "number" | "comment";

export interface CodeToken {
  kind: CodeTokenKind;
  text: string;
}

const HEADING_RE = /^(#{1,4})\s+(.*)$/;
const BULLET_RE = /^\s*[-*•]\s+(.*)$/;
const ORDERED_RE = /^\s*(\d+)[.)]\s+(.*)$/;
const INDENTED_RE = /^(?: {2,}|\t)/;
const FENCE_RE = /^\s*```\s*([\w+-]*)\s*$/;
const INLINE_RE = /(\*\*[^*\n]+\*\*)|(`[^`\n]+`)/g;
const CODE_SPAN_RE = /`[^`\n]+`/g;
const LINK_RE = /\[([^\]\n]+)\]\((https?:\/\/(?:[^\s()]|\([^\s()]*\))+)\)|https?:\/\/[^\s<>"`]+/gi;
// Разделитель шапки таблицы: `---`, `:---`, `:---:`, `---:` в каждой ячейке.
const TABLE_SEPARATOR_CELL_RE = /^:?-+:?$/;
const TABLE_CELL_SPLIT_RE = /(?<!\\)\|/;

/** Ссылки преобразуются только вне кода; пунктуация после URL остаётся текстом. */
export function linkParts(text: string, bold = false): InlinePart[] {
  const parts: InlinePart[] = [];
  let last = 0;
  for (const match of text.matchAll(LINK_RE)) {
    const index = match.index;
    let url = match[2] ?? match[0];
    // В свёрнутом превью обрезанный адрес не должен вести на другой ресурс.
    if (!match[2] && url.endsWith("…")) continue;
    if (!match[2]) {
      url = url.replace(/[.,!?;:\]}»”]+$/, "");
      while (url.endsWith(")") && (url.match(/\)/g)?.length ?? 0) > (url.match(/\(/g)?.length ?? 0)) {
        url = url.slice(0, -1);
      }
    }
    try {
      const parsed = new URL(url);
      if (!parsed.hostname || !["http:", "https:"].includes(parsed.protocol)) continue;
    } catch {
      continue;
    }
    if (index > last) parts.push({ kind: bold ? "bold" : "text", text: text.slice(last, index) });
    parts.push({ kind: "link", text: match[1] ?? url, href: url, ...(bold ? { bold: true } : {}) });
    last = index + (match[2] ? match[0].length : url.length);
  }
  if (last < text.length) parts.push({ kind: bold ? "bold" : "text", text: text.slice(last) });
  return parts;
}

/** Части жирного текста: код внутри остаётся кодом, но тоже жирным. */
function boldParts(text: string): InlinePart[] {
  const parts: InlinePart[] = [];
  let last = 0;
  for (const match of text.matchAll(CODE_SPAN_RE)) {
    const index = match.index ?? 0;
    if (index > last) parts.push(...linkParts(text.slice(last, index), true));
    parts.push({ kind: "code", text: match[0].slice(1, -1), bold: true });
    last = index + match[0].length;
  }
  if (last < text.length) parts.push(...linkParts(text.slice(last), true));
  return parts;
}

export function parseInline(text: string): InlinePart[] {
  const parts: InlinePart[] = [];
  let last = 0;
  for (const match of text.matchAll(INLINE_RE)) {
    const index = match.index ?? 0;
    if (index > last) parts.push(...linkParts(text.slice(last, index)));
    if (match[1]) parts.push(...boldParts(match[1].slice(2, -2)));
    else parts.push({ kind: "code", text: match[0].slice(1, -1) });
    last = index + match[0].length;
  }
  if (last < text.length) parts.push(...linkParts(text.slice(last)));
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
  // Номер следующего пункта открытого нумерованного списка; `null` — списка нет.
  // Блок кода, вложенный список и абзац внутри пункта список не закрывают: иначе
  // каждый пункт, оторванный от соседнего, снова получил бы «1.».
  let nextNumber: number | null = null;
  let blankBefore = false;

  const flushParagraph = () => {
    if (paragraph.length) blocks.push({ kind: "paragraph", parts: parseInline(paragraph.join("\n")) });
    paragraph = [];
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const wasBlank = blankBefore;
    blankBefore = !line.trim();
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
      nextNumber = null;
      blocks.push({ kind: "heading", level: heading[1].length, parts: parseInline(heading[2]) });
      continue;
    }
    const bullet = line.match(BULLET_RE);
    const ordered = bullet ? null : line.match(ORDERED_RE);
    if (bullet || ordered) {
      flushParagraph();
      const isOrdered = Boolean(ordered);
      const previous = blocks[blocks.length - 1];
      let start = 1;
      if (ordered) {
        // Пункт открытого списка получает следующий номер, даже если модель написала «1.».
        start = nextNumber ?? Number(ordered[1]);
        nextNumber = start + 1;
      } else if (!INDENTED_RE.test(line)) {
        // Маркированный список на уровне нумерованного закрывает его; вложенный — нет.
        nextNumber = null;
      }
      const item = parseInline((bullet ?? ordered)![bullet ? 1 : 2]);
      if (previous?.kind === "list" && previous.ordered === isOrdered) previous.items.push(item);
      else blocks.push({ kind: "list", ordered: isOrdered, items: [item], start });
      continue;
    }
    const table = parseTable(lines, i);
    if (table) {
      flushParagraph();
      nextNumber = null;
      blocks.push(table.block);
      i = table.next - 1;
      continue;
    }
    if (!line.trim()) {
      flushParagraph();
      continue;
    }
    // Абзац после пустой строки без отступа — уже не продолжение пункта.
    if (!paragraph.length && wasBlank && !INDENTED_RE.test(line)) nextNumber = null;
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
