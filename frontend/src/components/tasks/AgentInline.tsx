import type { InlinePart } from "@/lib/agentMarkdown";
import { cn } from "@/lib/utils";

/** Строчное оформление ответа агента: жирный текст и код (в том числе жирный). */
export function AgentInline({ parts }: { parts: InlinePart[] }) {
  return (
    <>
      {parts.map((part, index) => {
        if (part.kind === "bold") return <strong key={index} className="font-bold text-text">{part.text}</strong>;
        if (part.kind === "code")
          return (
            <code
              key={index}
              className={cn(
                "rounded bg-accent-tint px-1 py-px font-mono text-[0.9em] text-accent",
                part.bold && "font-bold",
              )}
            >
              {part.text}
            </code>
          );
        return <span key={index}>{part.text}</span>;
      })}
    </>
  );
}
