import type { InlinePart, TableAlign } from "@/lib/agentMarkdown";
import { cn } from "@/lib/utils";
import { AgentInline } from "@/components/tasks/AgentInline";

const ALIGN_CLASS: Record<TableAlign, string> = {
  left: "text-left",
  center: "text-center",
  right: "text-right",
};

const CELL_CLASS = "border border-border px-2.5 py-1 align-top";
// Колонка шириной по тексту, но не шире 40% ленты и не уже 28 символов: на
// широкой ленте таблица помещается, на узкой не сжимается до столбика слов.
const CELL_TEXT_CLASS = "max-w-[max(28ch,40cqw)] [overflow-wrap:anywhere]";

interface AgentMarkdownTableProps {
  align: TableAlign[];
  header: InlinePart[][];
  rows: InlinePart[][][];
}

/**
 * Таблица из ответа агента — рамкой, как её рисует Claude Code CLI: шапка
 * жирным, колонки выровнены по строке-разделителю; на узком экране таблица
 * прокручивается в своём блоке, а не растягивает страницу. Ширина колонки —
 * по тексту, с пределом под ширину ленты; длинный текст переносится в ячейке.
 */
export function AgentMarkdownTable({ align, header, rows }: AgentMarkdownTableProps) {
  return (
    <div className="@container max-w-full overflow-x-auto">
      <table className="w-max min-w-full border-collapse font-mono text-small">
        <thead>
          <tr>
            {header.map((cell, column) => (
              <th key={column} scope="col" className={cn(CELL_CLASS, "font-bold text-text", ALIGN_CLASS[align[column]])}>
                <div className={CELL_TEXT_CLASS}>
                  <AgentInline parts={cell} />
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, column) => (
                <td key={column} className={cn(CELL_CLASS, ALIGN_CLASS[align[column]])}>
                  <div className={CELL_TEXT_CLASS}>
                    <AgentInline parts={cell} />
                  </div>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
