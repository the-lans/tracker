import { highlightCode, parseMarkdown, type CodeTokenKind } from "@/lib/agentMarkdown";
import { cn } from "@/lib/utils";
import { AgentInline } from "@/components/tasks/AgentInline";
import { AgentMarkdownTable } from "@/components/tasks/AgentMarkdownTable";

// Та же палитра темы (--term-*), что у вывода скрипта (ScriptOutputText).
const CODE_TOKEN_CLASS: Record<CodeTokenKind, string> = {
  text: "",
  keyword: "text-term-keyword",
  string: "text-term-string",
  number: "text-term-number",
  comment: "italic text-term-comment",
};

/** Ответ агента в ленте: markdown-оформление, таблицы и подсветка блоков кода. */
export function AgentMessageText({ text }: { text: string }) {
  const blocks = parseMarkdown(text);
  return (
    <div className="flex min-w-0 max-w-full flex-col gap-2 whitespace-normal">
      {blocks.map((block, index) => {
        switch (block.kind) {
          case "heading":
            return (
              <div
                key={index}
                className={cn("font-extrabold text-text", block.level <= 2 ? "text-subtitle" : "text-lead")}
              >
                <AgentInline parts={block.parts} />
              </div>
            );
          case "list": {
            const ListTag = block.ordered ? "ol" : "ul";
            return (
              <ListTag
                key={index}
                className={cn(
                  "flex flex-col gap-1 pl-5 marker:text-accent",
                  block.ordered ? "list-decimal marker:font-bold" : "list-disc",
                )}
              >
                {block.items.map((item, itemIndex) => (
                  <li key={itemIndex}>
                    <AgentInline parts={item} />
                  </li>
                ))}
              </ListTag>
            );
          }
          case "code":
            return (
              <pre
                key={index}
                className="max-w-full overflow-x-auto rounded-lg border border-term-border bg-term-bg p-3 font-mono text-small leading-relaxed text-term-fg"
              >
                {block.language && (
                  <div className="mb-1 text-caption font-bold uppercase text-term-muted">{block.language}</div>
                )}
                <code>
                  {highlightCode(block.code).map((token, tokenIndex) => (
                    <span key={tokenIndex} className={CODE_TOKEN_CLASS[token.kind]}>
                      {token.text}
                    </span>
                  ))}
                </code>
              </pre>
            );
          case "table":
            return <AgentMarkdownTable key={index} align={block.align} header={block.header} rows={block.rows} />;
          default:
            return (
              <p key={index} className="whitespace-pre-wrap">
                <AgentInline parts={block.parts} />
              </p>
            );
        }
      })}
    </div>
  );
}
