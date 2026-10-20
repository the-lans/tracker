import { Copy, Download } from "lucide-react";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { STATUS_LABEL, STATUS_TONE, TRIGGER_LABEL } from "@/components/tasks/nodeLogLabels";
import { copyText, downloadText } from "@/lib/textExport";
import { formatDateTime } from "@/lib/utils";
import type { NodeLog } from "@/lib/types";

interface OutputSection {
  title: string;
  text: string;
}

function sectionsOf(log: NodeLog): OutputSection[] {
  const sections: Array<[string, string | null]> = [
    ["Промт", log.rendered_prompt],
    ["План", log.pending_plan_text],
    ["Ответ LLM", log.llm_output_text],
    [
      log.script_exit_code === null ? "Вывод скрипта" : `Вывод скрипта (код ${log.script_exit_code})`,
      log.script_stdout,
    ],
    ["Ввод пользователя", log.user_input_text],
  ];
  return sections
    .filter((section): section is [string, string] => Boolean(section[1]))
    .map(([title, text]) => ({ title, text }));
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
      <SheetContent className="md:inset-y-0 md:left-auto md:right-0 md:top-0 md:h-dvh md:max-h-none md:w-[560px] md:rounded-none md:border-l md:border-t-0">
        <SheetTitle className="pr-10 text-[15px] font-extrabold">{title}</SheetTitle>
        <div className="mt-1 flex flex-wrap items-center gap-2 text-[11.5px] text-text-3">
          <Badge tone={STATUS_TONE[log.status]}>{STATUS_LABEL[log.status]}</Badge>
          <span>{TRIGGER_LABEL[log.trigger_type]}</span>
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
          {sections.length === 0 && <div className="text-[12.5px] text-text-3">Вывода нет</div>}
          {sections.map((section) => (
            <section key={section.title}>
              <div className="mb-1 text-[11px] font-extrabold uppercase tracking-wider text-text-3">
                {section.title}
              </div>
              <div className="whitespace-pre-wrap rounded-lg bg-surface-2 p-3 font-mono text-[12px] leading-relaxed">
                {section.text}
              </div>
            </section>
          ))}
        </div>
      </SheetContent>
    </Sheet>
  );
}
