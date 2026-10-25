import { useState } from "react";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { DialogFooter } from "@/components/ui/dialog";
import { NodeExecutionFields } from "@/components/nodes/NodeExecutionFields";
import { PromptTemplateField } from "@/components/nodes/PromptTemplateField";
import { ScriptFields } from "@/components/nodes/ScriptFields";
import { SlashCommandField } from "@/components/nodes/SlashCommandField";
import type { NodeExecutionValues } from "@/components/nodes/nodeForm.types";
import { useCreateNode, useUpdateNode } from "@/hooks/useNodes";
import { toastError } from "@/lib/errors";
import { NodeType, ScriptLanguage, type NodeItem, type TemplatePreviewRequest } from "@/lib/types";
import { NODE_TYPE_LABEL } from "@/lib/labels";

const PIPELINE_ONLY_TYPES = Object.values(NodeType);
const LIBRARY_ALLOWED_TYPES = [NodeType.PLAIN_PROMPT, NodeType.SLASH_COMMAND, NodeType.SCRIPT];
const PROMPT_TYPES: readonly NodeType[] = [NodeType.PLAIN_PROMPT, NodeType.PLAN_PROMPT];

/** Раздел 15.4: общая форма для ноды пайплайна и промта библиотеки —
 * различие в наборе доступных полей, не в отдельных компонентах. */
export function NodeForm({
  mode,
  pipelineId,
  orderIndex,
  node,
  onSaved,
  onCancel,
}: {
  mode: "pipeline" | "library";
  pipelineId?: string;
  orderIndex?: number;
  node?: NodeItem;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const createNode = useCreateNode();
  // Хук вызывается безусловно (Rules of Hooks) — мутация фактически
  // выполняется только когда `node` определён (см. `handleSave`).
  const updateNode = useUpdateNode(node?.id ?? "");

  const [name, setName] = useState(node?.name ?? "");
  const [description, setDescription] = useState(node?.description ?? "");
  const [nodeType, setNodeType] = useState<NodeType>(node?.node_type ?? NodeType.PLAIN_PROMPT);
  const [promptTemplate, setPromptTemplate] = useState(node?.prompt_template ?? "");
  const [commandInvocation, setCommandInvocation] = useState(node?.command_invocation ?? "");
  const [scriptLanguage, setScriptLanguage] = useState<ScriptLanguage>(
    node?.script_language ?? ScriptLanguage.PYTHON,
  );
  const [scriptContent, setScriptContent] = useState(node?.script_content ?? "");
  const [guideUrl, setGuideUrl] = useState(node?.guide_url ?? "");
  const [execution, setExecution] = useState<NodeExecutionValues>({
    timeoutSeconds: node?.timeout_seconds ?? null,
    maxRetries: node?.max_retries ?? null,
    retryBaseDelaySeconds: node?.retry_base_delay_seconds ?? null,
    isSkipped: node?.is_skipped ?? false,
  });

  const isPipeline = mode === "pipeline";
  const availableTypes = isPipeline ? PIPELINE_ONLY_TYPES : LIBRARY_ALLOWED_TYPES;

  function previewRequest(): TemplatePreviewRequest {
    return isPipeline
      ? {
          text: promptTemplate,
          scope: "pipeline",
          node_id: node?.id ?? null,
          pipeline_id: pipelineId ?? null,
          order_index: orderIndex ?? node?.order_index ?? null,
        }
      : { text: promptTemplate, scope: "library" };
  }

  function handleSave() {
    const body = {
      pipeline_id: isPipeline ? pipelineId : null,
      order_index: isPipeline ? (orderIndex ?? node?.order_index ?? 0) : null,
      name,
      description: description || null,
      node_type: nodeType,
      prompt_template: PROMPT_TYPES.includes(nodeType) ? promptTemplate : null,
      command_invocation: nodeType === NodeType.SLASH_COMMAND ? commandInvocation : null,
      script_language: nodeType === NodeType.SCRIPT ? scriptLanguage : null,
      script_content: nodeType === NodeType.SCRIPT ? scriptContent : null,
      guide_url: guideUrl || null,
      timeout_seconds: execution.timeoutSeconds,
      max_retries: isPipeline ? execution.maxRetries : undefined,
      retry_base_delay_seconds: isPipeline ? execution.retryBaseDelaySeconds : undefined,
      is_skipped: isPipeline ? execution.isSkipped : false,
    };
    const callbacks = { onSuccess: onSaved, onError: toastError("Не удалось сохранить ноду") };
    if (node) {
      updateNode.mutate(body, callbacks);
    } else {
      createNode.mutate(body, callbacks);
    }
  }

  const isPending = createNode.isPending || updateNode.isPending;

  return (
    <div className="flex flex-col gap-3">
      <div>
        <Label htmlFor="node-name">Название</Label>
        <Input id="node-name" value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div>
        <Label htmlFor="node-description">
          Описание{mode === "library" ? " (обязательно)" : ""}
        </Label>
        <Textarea
          id="node-description"
          rows={2}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>
      <div>
        <Label htmlFor="node-type">Тип ноды</Label>
        <Select value={nodeType} onValueChange={(v) => setNodeType(v as NodeType)}>
          <SelectTrigger id="node-type">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {availableTypes.map((type) => (
              <SelectItem key={type} value={type}>
                {NODE_TYPE_LABEL[type]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {nodeType === NodeType.PLAN_PROMPT && (
        <div className="rounded-md border border-info-tint bg-info-tint px-3 py-2 text-note text-info-text">
          Нода доступна только внутри пайплайна и не может быть сохранена как элемент библиотеки.
        </div>
      )}

      {PROMPT_TYPES.includes(nodeType) && (
        <PromptTemplateField
          value={promptTemplate}
          onChange={setPromptTemplate}
          allowNodeVariables={isPipeline}
          previewRequest={previewRequest}
        />
      )}

      {nodeType === NodeType.SLASH_COMMAND && (
        <SlashCommandField value={commandInvocation} onChange={setCommandInvocation} />
      )}

      {nodeType === NodeType.SCRIPT && (
        <ScriptFields
          language={scriptLanguage}
          content={scriptContent}
          onLanguageChange={setScriptLanguage}
          onContentChange={setScriptContent}
        />
      )}

      <div>
        <Label htmlFor="node-guide">Гайд (URL Confluence)</Label>
        <Input id="node-guide" value={guideUrl} onChange={(e) => setGuideUrl(e.target.value)} />
      </div>

      <NodeExecutionFields
        values={execution}
        withRetries={isPipeline}
        onChange={(patch) => setExecution((current) => ({ ...current, ...patch }))}
      />

      <DialogFooter>
        <Button type="button" variant="secondary" onClick={onCancel}>
          Отмена
        </Button>
        <Button
          type="button"
          onClick={handleSave}
          disabled={!name || (mode === "library" && !node && !description.trim()) || isPending}
        >
          Сохранить
        </Button>
      </DialogFooter>
    </div>
  );
}
