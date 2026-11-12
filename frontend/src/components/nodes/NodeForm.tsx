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
import { LibrarySourceField } from "@/components/nodes/LibrarySourceField";
import { NodeEffortField } from "@/components/nodes/NodeEffortField";
import { NodeExecutionFields } from "@/components/nodes/NodeExecutionFields";
import { PromptTemplateField } from "@/components/nodes/PromptTemplateField";
import { ScriptFields } from "@/components/nodes/ScriptFields";
import { SlashCommandField } from "@/components/nodes/SlashCommandField";
import {
  NodeSource,
  type LibrarySourceValue,
  type NodeExecutionValues,
} from "@/components/nodes/nodeForm.types";
import { useCreateNode, useUpdateNode } from "@/hooks/useNodes";
import { toastError } from "@/lib/errors";
import {
  NodeType,
  ScriptLanguage,
  type NodeItem,
  type ReasoningEffort,
  type TemplatePreviewRequest,
} from "@/lib/types";
import { NODE_TYPE_LABEL } from "@/lib/labels";

const PIPELINE_ONLY_TYPES = Object.values(NodeType);
const LIBRARY_ALLOWED_TYPES = [NodeType.PLAIN_PROMPT, NodeType.SLASH_COMMAND, NodeType.SCRIPT];
const PROMPT_TYPES: readonly NodeType[] = [NodeType.PLAIN_PROMPT, NodeType.PLAN_PROMPT];
/** Раздел 11.1: уровень рассуждений — у нод, которые выполняет модель. */
const EFFORT_TYPES: readonly NodeType[] = [
  NodeType.PLAIN_PROMPT,
  NodeType.SLASH_COMMAND,
  NodeType.PLAN_PROMPT,
];

/** Раздел 15.4: общая форма для ноды пайплайна и промта библиотеки —
 * различие в наборе доступных полей, не в отдельных компонентах. */
export function NodeForm({
  mode,
  pipelineId,
  pipelineOwnerId,
  orderIndex,
  node,
  onSaved,
  onCancel,
}: {
  mode: "pipeline" | "library";
  pipelineId?: string;
  /** Автор пайплайна: нода ссылается только на его библиотеку (раздел 7.6). */
  pipelineOwnerId?: string;
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
  const [slashName, setSlashName] = useState(node?.slash_name ?? "");
  const [argumentHint, setArgumentHint] = useState(node?.argument_hint ?? "");
  const [description, setDescription] = useState(node?.description ?? "");
  const [nodeType, setNodeType] = useState<NodeType>(node?.node_type ?? NodeType.PLAIN_PROMPT);
  const [promptTemplate, setPromptTemplate] = useState(node?.prompt_template ?? "");
  const [commandInvocation, setCommandInvocation] = useState(node?.command_invocation ?? "");
  const [scriptLanguage, setScriptLanguage] = useState<ScriptLanguage>(
    node?.script_language ?? ScriptLanguage.PYTHON,
  );
  const [scriptContent, setScriptContent] = useState(node?.script_content ?? "");
  const [guideUrl, setGuideUrl] = useState(node?.guide_url ?? "");
  const [effort, setEffort] = useState<ReasoningEffort | null>(node?.reasoning_effort ?? null);
  const [execution, setExecution] = useState<NodeExecutionValues>({
    timeoutSeconds: node?.timeout_seconds ?? null,
    maxRetries: node?.max_retries ?? null,
    retryBaseDelaySeconds: node?.retry_base_delay_seconds ?? null,
    isSkipped: node?.is_skipped ?? false,
  });

  const [librarySource, setLibrarySource] = useState<LibrarySourceValue>({
    source: node?.library_node_id ? NodeSource.LIBRARY : NodeSource.OWN,
    libraryNodeId: node?.library_node_id ?? null,
    libraryNodeType: node?.library_node_id ? node.node_type : null,
    arguments: node?.library_arguments ?? "",
  });

  const isPipeline = mode === "pipeline";
  const availableTypes = isPipeline ? PIPELINE_ONLY_TYPES : LIBRARY_ALLOWED_TYPES;
  const linked = isPipeline && librarySource.source === NodeSource.LIBRARY;
  const effectiveType = linked ? (librarySource.libraryNodeType ?? nodeType) : nodeType;
  const withGuide = !linked && nodeType === NodeType.PLAIN_PROMPT;

  function previewRequest(): TemplatePreviewRequest {
    const guide = withGuide ? { guide_url: guideUrl || null } : {};
    return isPipeline
      ? {
          text: promptTemplate,
          scope: "pipeline",
          node_id: node?.id ?? null,
          pipeline_id: pipelineId ?? null,
          order_index: orderIndex ?? node?.order_index ?? null,
          ...guide,
        }
      : { text: promptTemplate, scope: "library", ...guide };
  }

  /** Содержимое ноды: своё или ссылка на промт библиотеки (поля содержимого тогда пусты). */
  function contentFields() {
    if (linked) {
      return {
        node_type: effectiveType,
        prompt_template: null,
        command_invocation: null,
        script_language: null,
        script_content: null,
        guide_url: null,
        library_node_id: librarySource.libraryNodeId,
        library_arguments: librarySource.arguments.trim() || null,
      };
    }
    return {
      node_type: nodeType,
      prompt_template: PROMPT_TYPES.includes(nodeType) ? promptTemplate : null,
      command_invocation: nodeType === NodeType.SLASH_COMMAND ? commandInvocation : null,
      script_language: nodeType === NodeType.SCRIPT ? scriptLanguage : null,
      script_content: nodeType === NodeType.SCRIPT ? scriptContent : null,
      guide_url: withGuide ? guideUrl || null : null,
      ...(isPipeline ? { library_node_id: null, library_arguments: null } : {}),
    };
  }

  function handleSave() {
    const body = {
      pipeline_id: isPipeline ? pipelineId : null,
      order_index: isPipeline ? (orderIndex ?? node?.order_index ?? 0) : null,
      name,
      description: description || null,
      ...(!isPipeline && (nodeType === NodeType.PLAIN_PROMPT || nodeType === NodeType.SCRIPT) && (slashName.trim() || node?.slash_name) ? {
        slash_name: slashName.trim() || null,
        argument_hint: slashName.trim() ? argumentHint.trim() || null : null,
      } : {}),
      ...contentFields(),
      timeout_seconds: execution.timeoutSeconds,
      max_retries: isPipeline ? execution.maxRetries : undefined,
      retry_base_delay_seconds: isPipeline ? execution.retryBaseDelaySeconds : undefined,
      is_skipped: isPipeline ? execution.isSkipped : false,
      reasoning_effort: EFFORT_TYPES.includes(effectiveType) ? effort : null,
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
      {!isPipeline && (nodeType === NodeType.PLAIN_PROMPT || nodeType === NodeType.SCRIPT) && <>
        <div><Label htmlFor="node-slash-name">Slash-команда (необязательно)</Label>
          <Input id="node-slash-name" placeholder="/review" maxLength={65}
            value={slashName} onChange={(event) => setSlashName(event.target.value)} />
          <p className="text-small text-text-3">Доступна во всех ваших задачах. Имеет приоритет над одноимённой командой агента.</p>
        </div>
        <div><Label htmlFor="node-argument-hint">Подсказка аргументов</Label>
          <Input id="node-argument-hint" placeholder="[сервис] [что проверить]" maxLength={200}
            value={argumentHint} disabled={!slashName.trim()}
            onChange={(event) => setArgumentHint(event.target.value)} />
          <p className="text-small text-text-3">{nodeType === NodeType.SCRIPT
            ? "Bash: $1, $2 и \"$@\"; Python: sys.argv[1:]. Полный текст: TRACKER_COMMAND_ARGUMENTS."
            : "В промте: $ARGUMENTS — весь текст; $1 или $ARGUMENTS[1] — первый аргумент, $2 — второй."}</p>
        </div>
      </>}
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
      {isPipeline && (
        <LibrarySourceField
          ownerId={pipelineOwnerId ?? node?.created_by}
          value={librarySource}
          onChange={setLibrarySource}
        />
      )}
      {!linked && <>
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
            withGuideVariable={nodeType === NodeType.PLAIN_PROMPT}
            previewRequest={previewRequest}
            argumentHint={
              !isPipeline && nodeType === NodeType.PLAIN_PROMPT && slashName.trim()
                ? argumentHint.trim()
                : undefined
            }
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

        {withGuide && (
          <div>
            <Label htmlFor="node-guide">Гайд (URL Confluence)</Label>
            <Input id="node-guide" value={guideUrl} onChange={(e) => setGuideUrl(e.target.value)} />
            <p className="mt-1 text-small text-text-3">В тексте промта — {"{{node.guide_url}}"}.</p>
          </div>
        )}
      </>}

      {EFFORT_TYPES.includes(effectiveType) && (
        <NodeEffortField id="node-effort" value={effort} onChange={setEffort} />
      )}

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
          disabled={
            !name ||
            (mode === "library" && !node && !description.trim()) ||
            (linked && !librarySource.libraryNodeId) ||
            isPending
          }
        >
          Сохранить
        </Button>
      </DialogFooter>
    </div>
  );
}
