import { useState } from "react";
import { PromptTemplateField } from "@/components/nodes/PromptTemplateField";
import { SlashCommandField } from "@/components/nodes/SlashCommandField";
import { Button } from "@/components/ui/button";
import { DialogFooter } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useNodes } from "@/hooks/useNodes";
import { NODE_TYPE_LABEL } from "@/lib/labels";
import {
  NodeType,
  type NodeItem,
  type TaskCustomNodeContent,
  type TemplatePreviewRequest,
} from "@/lib/types";

/** Раздел 13.1: свой промт задачи — промт или слэш-команда. */
const CUSTOM_NODE_TYPES: readonly NodeType[] = [NodeType.PLAIN_PROMPT, NodeType.SLASH_COMMAND];

function isCustomNodeType(type: NodeType): boolean {
  return CUSTOM_NODE_TYPES.includes(type);
}

/** Раздел 13.1, 15.2: форма своего промта; текст можно взять копией из библиотеки. */
export function TaskCustomNodeForm({
  taskId,
  orderIndex,
  initial,
  nodeId,
  pending,
  onSubmit,
  onCancel,
}: {
  taskId: string;
  /** Позиция ноды в составе задачи — задаёт доступные `{{node.*}}` в предпросмотре. */
  orderIndex: number;
  initial?: TaskCustomNodeContent;
  /** Сохранённая своя нода: предпросмотр не считает её саму предыдущей. */
  nodeId?: string;
  pending: boolean;
  onSubmit: (content: TaskCustomNodeContent) => void;
  onCancel: () => void;
}) {
  const { data: libraryNodes } = useNodes({ libraryOnly: true });
  const [name, setName] = useState(initial?.name ?? "");
  const [nodeType, setNodeType] = useState<NodeType>(
    initial?.node_type ?? NodeType.PLAIN_PROMPT,
  );
  const [promptTemplate, setPromptTemplate] = useState(
    initial?.prompt_template ?? "",
  );
  const [commandInvocation, setCommandInvocation] = useState(
    initial?.command_invocation ?? "",
  );
  const isCommand = nodeType === NodeType.SLASH_COMMAND;
  const text = isCommand ? commandInvocation : promptTemplate;
  const sources = (libraryNodes ?? []).filter((node) =>
    isCustomNodeType(node.node_type),
  );

  function fillFrom(source: NodeItem) {
    setName(source.name);
    setNodeType(source.node_type);
    setPromptTemplate(source.prompt_template ?? "");
    setCommandInvocation(source.command_invocation ?? "");
  }

  function previewRequest(): TemplatePreviewRequest {
    return {
      text: promptTemplate,
      scope: "pipeline",
      task_id: taskId,
      node_id: nodeId ?? null,
      order_index: orderIndex,
    };
  }

  function handleSubmit() {
    onSubmit({
      name: name.trim(),
      node_type: nodeType,
      prompt_template: isCommand ? null : promptTemplate,
      command_invocation: isCommand ? commandInvocation : null,
    });
  }

  return (
    <div className="flex flex-col gap-3">
      {sources.length > 0 && (
        <div>
          <Label htmlFor="custom-node-source">Заполнить из библиотеки</Label>
          <Select
            value=""
            onValueChange={(id) => {
              const source = sources.find((node) => node.id === id);
              if (source) fillFrom(source);
            }}
          >
            <SelectTrigger id="custom-node-source">
              <SelectValue placeholder="Выберите промт — текст скопируется" />
            </SelectTrigger>
            <SelectContent>
              {sources.map((node) => (
                <SelectItem key={node.id} value={node.id}>
                  {node.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}
      <div>
        <Label htmlFor="custom-node-name">Название</Label>
        <Input
          id="custom-node-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </div>
      <div>
        <Label htmlFor="custom-node-type">Тип</Label>
        <Select
          value={nodeType}
          onValueChange={(value) => setNodeType(value as NodeType)}
        >
          <SelectTrigger id="custom-node-type">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {CUSTOM_NODE_TYPES.map((type) => (
              <SelectItem key={type} value={type}>
                {NODE_TYPE_LABEL[type]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {isCommand ? (
        <SlashCommandField
          value={commandInvocation}
          onChange={setCommandInvocation}
        />
      ) : (
        <PromptTemplateField
          value={promptTemplate}
          onChange={setPromptTemplate}
          allowNodeVariables
          previewRequest={previewRequest}
        />
      )}
      <DialogFooter>
        <Button variant="secondary" onClick={onCancel}>
          Отмена
        </Button>
        <Button
          onClick={handleSubmit}
          disabled={pending || !name.trim() || !text.trim()}
        >
          Сохранить
        </Button>
      </DialogFooter>
    </div>
  );
}
