import type { InlinePart, TableAlign } from "@/lib/agentMarkdown";
import { cn } from "@/lib/utils";
import { AgentInline } from "@/components/tasks/AgentInline";

const ALIGN_CLASS: Record<TableAlign, string> = {
  left: "text-left",
  center: "text-center",
  right: "text-right",
};

const CELL_CLASS = "border border-border px-2.5 py-1 align-top";

interface AgentMarkdownTableProps {
  align: TableAlign[];
  header: InlinePart[][];
  rows: InlinePart[][][];
}

/**
 * Таблица из ответа агента — рамкой, как её рисует Claude Code CLI: шапка
 * жирным, колонки выровнены по строке-разделителю; на узком экране таблица
 * прокручивается в своём блоке, а не растягивает страницу.
 */
export function AgentMarkdownTable({ align, header, rows }: AgentMarkdownTableProps) {
  return (
    <div className="max-w-full overflow-x-auto">
      <table className="border-collapse font-mono text-small [overflow-wrap:normal]">
        <thead>
          <tr>
            {header.map((cell, column) => (
              <th key={column} scope="col" className={cn(CELL_CLASS, "font-bold text-text", ALIGN_CLASS[align[column]])}>
                <AgentInline parts={cell} />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, column) => (
                <td key={column} className={cn(CELL_CLASS, ALIGN_CLASS[align[column]])}>
                  <AgentInline parts={cell} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
