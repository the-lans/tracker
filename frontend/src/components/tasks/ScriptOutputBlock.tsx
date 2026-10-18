import { CollapsibleText } from "@/components/tasks/CollapsibleText";

export function ScriptOutputBlock({
  stdout,
  exitCode,
}: {
  stdout: string | null;
  exitCode: number | null;
}) {
  return (
    <div className="max-w-[560px] rounded-xl bg-[#14151d] p-3.5 text-[#c9cbe0]">
      <div className="mb-2 flex items-center justify-between text-[11px] font-bold text-[#8b8ea8]">
        <span>ВЫВОД СКРИПТА</span>
        <span>{exitCode === null ? "выполняется…" : `exit ${exitCode}`}</span>
      </div>
      <CollapsibleText text={stdout ?? "(пусто)"} monospace filename="script-output.txt" />
    </div>
  );
}
