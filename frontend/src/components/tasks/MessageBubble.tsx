import { cn } from "@/lib/utils";
import { CollapsibleText } from "@/components/tasks/CollapsibleText";
import { AgentMessageText } from "@/components/tasks/AgentMessageText";
import { MESSAGE_KINDS, type MessageKind } from "@/components/tasks/messageKinds";
import { USER_AVATAR_GRADIENT } from "@/styles/classes";

/**
 * Источник реплики показывает заголовок записи и значок кружка. `streaming` —
 * ответ ещё генерируется (раздел 15.2). Реплики из `claude.ai/code` в ленту
 * не попадают: там сессия доступна только для просмотра (раздел 6.3).
 */

export function MessageBubble({
  role,
  text,
  danger,
  streaming = false,
  thinking = false,
  defaultExpanded = false,
  kind = role === "user" ? "manual" : danger ? "error" : "agent",
}: {
  role: "user" | "llm";
  text: string;
  danger?: boolean;
  streaming?: boolean;
  /** Агент думает: первый фрагмент ответа ещё не пришёл (раздел 15.2). */
  thinking?: boolean;
  /** Показать текст целиком, без превью (ответ, увиденный в потоке). */
  defaultExpanded?: boolean;
  /** Значок кружка: источник запроса или вид ответа. */
  kind?: MessageKind;
}) {
  const { icon: KindIcon, title: kindTitle } = MESSAGE_KINDS[kind];
  return (
    <div className={cn("flex min-w-0 max-w-[min(640px,100%)] gap-2.5", role === "user" && "ml-auto flex-row-reverse")}>
      {/* Значок по источнику реплики; цвета — с заметной рамкой, чтобы кружок не сливался с фоном. */}
      <div
        role="img"
        aria-label={kindTitle}
        title={kindTitle}
        className={cn(
          "flex size-7 shrink-0 items-center justify-center rounded-full",
          role === "user" && USER_AVATAR_GRADIENT,
          role === "llm" && !danger && "border border-accent-border bg-accent-tint text-accent",
          role === "llm" && danger && "border border-danger/40 bg-danger-tint text-danger-text",
        )}
      >
        <KindIcon className="size-3.5" />
      </div>
      <div className="min-w-0">
        <div
          className={cn(
            "min-w-0 max-w-full rounded-[14px] px-3.5 py-2.5 text-body-lg leading-relaxed",
            role === "llm" && "rounded-tl-[4px] border border-border bg-surface text-text",
            role === "user" && "rounded-tr-[4px] border border-accent-border bg-accent-tint text-text",
            danger && "border-danger-border bg-danger-tint text-danger-text",
          )}
        >
          {thinking ? (
            <div role="status" className="text-text-3">
              думает…
            </div>
          ) : (
            <CollapsibleText
              text={text}
              live={streaming}
              defaultExpanded={defaultExpanded}
              renderText={
                role === "llm" && !danger ? (shown) => <AgentMessageText text={shown} /> : undefined
              }
            />
          )}
        </div>
        {streaming && (
          <div className="mt-1 text-caption font-bold text-text-3" aria-live="polite">
            генерируется…
          </div>
        )}
      </div>
    </div>
  );
}
