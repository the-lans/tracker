import { Sparkles } from "lucide-react";
import { CollapsibleText } from "@/components/tasks/CollapsibleText";

export function PlanCard({ text }: { text: string }) {
  return (
    <div
      className="max-w-[640px] rounded-2xl border border-accent-border p-4"
      style={{ background: "linear-gradient(180deg, var(--accent-tint), var(--surface))" }}
    >
      <div className="mb-2.5 flex items-center gap-2 text-[12px] font-extrabold uppercase tracking-wide text-accent-hov">
        <Sparkles className="size-3.5" />
        План сформирован
      </div>
      <div className="text-[13.5px] leading-relaxed text-text">
        <CollapsibleText text={text} />
      </div>
    </div>
  );
}
