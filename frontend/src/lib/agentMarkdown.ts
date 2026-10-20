/**
 * Небольшой разбор markdown-ответа агента для ленты: только то, что агент
 * реально присылает (заголовки, списки, жирный, код). Результат — дерево
 * данных, отрисовка идёт React-элементами, поэтому HTML из ответа не
 * исполняется.
 */

export type InlineKind = "text" | "bold" | "code";

export interface InlinePart {
  kind: InlineKind;
  text: string;
}

export type MarkdownBlock =
  | { kind: "heading"; level: number; parts: InlinePart[] }
  | { kind: "paragraph"; parts: InlinePart[] }
  | { kind: "list"; ordered: boolean; items: InlinePart[][] }
  | { kind: "code"; language: string; code: string };

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

export function parseInline(text: string): InlinePart[] {
  const parts: InlinePart[] = [];
  let last = 0;
  for (const match of text.matchAll(INLINE_RE)) {
    const index = match.index ?? 0;
    if (index > last) parts.push({ kind: "text", text: text.slice(last, index) });
    parts.push(
      match[1]
        ? { kind: "bold", text: match[1].slice(2, -2) }
        : { kind: "code", text: match[0].slice(1, -1) },
    );
    last = index + match[0].length;
  }
  if (last < text.length) parts.push({ kind: "text", text: text.slice(last) });
  return parts;
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
