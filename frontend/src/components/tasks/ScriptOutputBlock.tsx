import { CollapsibleText } from "@/components/tasks/CollapsibleText";
import { ScriptOutputText } from "@/components/tasks/ScriptOutputText";
import { cn } from "@/lib/utils";

function exitCodeClass(exitCode: number | null): string {
  if (exitCode === null) return "text-term-muted";
  return exitCode === 0 ? "text-term-success" : "text-term-error";
}

export function ScriptOutputBlock({
  stdout,
  exitCode,
}: {
  stdout: string | null;
  exitCode: number | null;
}) {
  return (
    <div className="max-w-[560px] rounded-xl border border-term-border bg-term-bg p-3.5 text-term-fg">
      <div className="mb-2 flex items-center justify-between text-caption font-bold text-term-muted">
        <span>ВЫВОД СКРИПТА</span>
        <span className={cn("flex items-center gap-1.5", exitCodeClass(exitCode))}>
          {exitCode !== null && <span className="size-1.5 rounded-full bg-current" aria-hidden />}
          {exitCode === null ? "выполняется…" : `exit ${exitCode}`}
        </span>
      </div>
      <CollapsibleText
        text={stdout ?? "(пусто)"}
        monospace
        filename="script-output.txt"
        renderText={(text) => <ScriptOutputText text={text} />}
      />
    </div>
  );
}
