import { Copy, Download } from "lucide-react";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { NODE_LOG_STATUS_LABEL, NODE_LOG_STATUS_TONE, NODE_LOG_TRIGGER_LABEL } from "@/lib/labels";
import { copyText, downloadText } from "@/lib/textExport";
import { cn, formatDateTime } from "@/lib/utils";
import { ScriptOutputText } from "@/components/tasks/ScriptOutputText";
import { AgentMessageText } from "@/components/tasks/AgentMessageText";
import { describeUserInput } from "@/lib/userInput";
import type { NodeLog } from "@/lib/types";

type SectionView = "plain" | "agent" | "script";

interface OutputSection {
  title: string;
  text: string;
  view: SectionView;
}

function sectionsOf(log: NodeLog): OutputSection[] {
  const sections: Array<[string, string | null, SectionView]> = [
    ["Промт", log.rendered_prompt, "plain"],
    ["План", log.pending_plan_text, "agent"],
    ["Ответ LLM", log.llm_output_text, "agent"],
    [
      log.script_exit_code === null ? "Вывод скрипта" : `Вывод скрипта (код ${log.script_exit_code})`,
      log.script_stdout,
      "script",
    ],
    ["Ввод пользователя", log.user_input_text ? describeUserInput(log).text : null, "plain"],
  ];
  return sections
    .filter((section): section is [string, string, SectionView] => Boolean(section[1]))
    .map(([title, text, view]) => ({ title, text, view }));
}

/** Раздел 15.2, 15.3: полный вывод одной записи — боковая панель на
 * десктопе, выезжающая снизу на мобильном; копирование и скачивание. */
export function NodeOutputSheet({
  log,
  title,
  open,
  onOpenChange,
}: {
  log: NodeLog;
  title: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const sections = sectionsOf(log);
  const fullText = sections.map((section) => `## ${section.title}\n\n${section.text}`).join("\n\n");

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="md:[&>[data-sheet-handle]]:hidden md:inset-y-0 md:left-auto md:right-0 md:top-0 md:h-dvh md:max-h-none md:w-[560px] md:rounded-none md:border-l md:border-t-0">
        <SheetTitle className="pr-10 text-subtitle font-extrabold">{title}</SheetTitle>
        <div className="mt-1 flex flex-wrap items-center gap-2 text-meta text-text-3">
          <Badge tone={NODE_LOG_STATUS_TONE[log.status]}>{NODE_LOG_STATUS_LABEL[log.status]}</Badge>
          <span>{NODE_LOG_TRIGGER_LABEL[log.trigger_type]}</span>
          <span>попытка {log.attempt_number}</span>
          <span>{formatDateTime(log.started_at)}</span>
        </div>
        <div className="mt-3 flex gap-2">
          <Button size="sm" variant="secondary" disabled={!fullText} onClick={() => copyText(fullText)}>
            <Copy className="size-3.5" /> Копировать
          </Button>
          <Button
            size="sm"
            variant="secondary"
            disabled={!fullText}
            onClick={() => downloadText(fullText, `node-log-${log.id}.md`)}
          >
            <Download className="size-3.5" /> Скачать
          </Button>
        </div>
        <div className="mt-4 flex flex-col gap-4">
          {sections.length === 0 && <div className="text-note text-text-3">Вывода нет</div>}
          {sections.map((section) => (
            <section key={section.title}>
              <div className="mb-1 text-caption font-extrabold uppercase tracking-wider text-text-3">
                {section.title}
              </div>
              <div
                className={cn(
                  "whitespace-pre-wrap rounded-lg p-3 leading-relaxed [overflow-wrap:anywhere]",
                  section.view === "agent" ? "bg-surface-2 text-body" : "font-mono text-small",
                  section.view === "script" && "border border-term-border bg-term-bg text-term-fg",
                  section.view === "plain" && "bg-surface-2",
                )}
              >
                {section.view === "script" && <ScriptOutputText text={section.text} />}
                {section.view === "agent" && <AgentMessageText text={section.text} />}
                {section.view === "plain" && section.text}
              </div>
            </section>
          ))}
        </div>
      </SheetContent>
    </Sheet>
  );
}
