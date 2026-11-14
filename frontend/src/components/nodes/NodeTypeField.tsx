import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { LIBRARY_PROMPT_TYPE, type NodeFormType } from "@/components/nodes/nodeForm.types";
import { LIBRARY_PROMPT_LABEL, NODE_TYPE_LABEL } from "@/lib/labels";
import { NodeType } from "@/lib/types";

function typeLabel(type: NodeFormType): string {
  return type === LIBRARY_PROMPT_TYPE ? LIBRARY_PROMPT_LABEL : NODE_TYPE_LABEL[type];
}

/** Тип ноды; у «Режима планирования» — подсказка, что он только для пайплайна. */
export function NodeTypeField({
  value,
  types,
  onChange,
}: {
  value: NodeFormType;
  types: readonly NodeFormType[];
  onChange: (value: NodeFormType) => void;
}) {
  return (
    <>
      <div>
        <Label htmlFor="node-type">Тип ноды</Label>
        <Select value={value} onValueChange={(v) => onChange(v as NodeFormType)}>
          <SelectTrigger id="node-type">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {types.map((type) => (
              <SelectItem key={type} value={type}>
                {typeLabel(type)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {value === NodeType.PLAN_PROMPT && (
        <div className="rounded-md border border-info-tint bg-info-tint px-3 py-2 text-note text-info-text">
          Нода доступна только внутри пайплайна и не может быть сохранена как элемент библиотеки.
        </div>
      )}
    </>
  );
}
