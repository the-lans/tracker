import { Radio } from "lucide-react";
import { cn } from "@/lib/utils";
import { CollapsibleText } from "@/components/tasks/CollapsibleText";

/**
 * `sourceLabel` — метка источника реплики (раздел 8.2: «отправлено
 * вручную»; раздел 15.2: сообщения из claude.ai/code). Канал claude.ai/code
 * `node_logs` пока не хранит — эта метка появится вместе с полем в API.
 */

export function MessageBubble({
  role,
  text,
  danger,
  sourceLabel,
}: {
  role: "user" | "llm";
  text: string;
  danger?: boolean;
  sourceLabel?: string;
}) {
  return (
    <div className={cn("flex max-w-[640px] gap-2.5", role === "user" && "ml-auto flex-row-reverse")}>
      <div
        className={cn(
          "size-7 shrink-0 rounded-full bg-surface-2",
          role === "user" && "bg-gradient-to-br from-[#8b7bf0] to-accent",
        )}
      />
      <div className="min-w-0">
        {sourceLabel && (
          <div className="mb-1 flex items-center gap-1.5 text-[10.5px] font-bold text-info-text">
            <Radio className="size-2.5" />
            {sourceLabel}
          </div>
        )}
        <div
          className={cn(
            "rounded-[14px] px-3.5 py-2.5 text-[13.5px] leading-relaxed",
            role === "llm" && "rounded-tl-[4px] border border-border bg-surface text-text",
            role === "user" && "rounded-tr-[4px] bg-accent text-white",
            danger && "border-danger-border bg-danger-tint text-danger-text",
          )}
        >
          <CollapsibleText text={text} />
        </div>
      </div>
    </div>
  );
}
