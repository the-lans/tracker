import { Sparkles } from "lucide-react";
import { CollapsibleText } from "@/components/tasks/CollapsibleText";
import { AgentMessageText } from "@/components/tasks/AgentMessageText";

/** План на ревью — полным текстом над виджетом выбора (раздел 15.2). */
export function PlanCard({ text }: { text: string }) {
  return (
    <div
      className="max-w-[640px] rounded-2xl border border-accent-border p-4"
      style={{ background: "linear-gradient(180deg, var(--accent-tint), var(--surface))" }}
    >
      <div className="mb-2.5 flex items-center gap-2 text-small font-extrabold uppercase tracking-wide text-accent-hov">
        <Sparkles className="size-3.5" />
        План сформирован
      </div>
      <div className="text-body-lg leading-relaxed text-text">
        <CollapsibleText text={text} defaultExpanded renderText={(shown) => <AgentMessageText text={shown} />} />
      </div>
    </div>
  );
}
