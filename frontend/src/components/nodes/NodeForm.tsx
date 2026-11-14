import { useState } from "react";
import { Checkbox } from "@/components/ui/checkbox";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { DialogFooter } from "@/components/ui/dialog";
import { LibraryPromptFields } from "@/components/nodes/LibraryPromptFields";
import { NodeGuideField } from "@/components/nodes/NodeGuideField";
import { NodeTypeField } from "@/components/nodes/NodeTypeField";
import {
  PROMPT_TYPES,
  linkedContentPayload,
  ownContentPayload,
} from "@/components/nodes/nodeContent";
import { NodeEffortField } from "@/components/nodes/NodeEffortField";
import { PromptTemplateField } from "@/components/nodes/PromptTemplateField";
import { ScriptFields } from "@/components/nodes/ScriptFields";
import { SlashCommandField } from "@/components/nodes/SlashCommandField";
import {
  LIBRARY_PROMPT_TYPE,
  type LibraryLinkValue,
  type NodeFormType,
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

const PIPELINE_TYPES: readonly NodeFormType[] = [...Object.values(NodeType), LIBRARY_PROMPT_TYPE];
const LIBRARY_ALLOWED_TYPES: readonly NodeFormType[] = [
  NodeType.PLAIN_PROMPT,
  NodeType.SLASH_COMMAND,
  NodeType.SCRIPT,
];
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
  const [formType, setFormType] = useState<NodeFormType>(
    node?.library_node_id ? LIBRARY_PROMPT_TYPE : (node?.node_type ?? NodeType.PLAIN_PROMPT),
  );
  const [promptTemplate, setPromptTemplate] = useState(node?.prompt_template ?? "");
  const [commandInvocation, setCommandInvocation] = useState(node?.command_invocation ?? "");
  const [scriptLanguage, setScriptLanguage] = useState<ScriptLanguage>(
    node?.script_language ?? ScriptLanguage.PYTHON,
  );
  const [scriptContent, setScriptContent] = useState(node?.script_content ?? "");
  const [guideUrl, setGuideUrl] = useState(node?.guide_url ?? "");
  const [effort, setEffort] = useState<ReasoningEffort | null>(node?.reasoning_effort ?? null);
  const [isSkipped, setIsSkipped] = useState(node?.is_skipped ?? false);

  const [libraryLink, setLibraryLink] = useState<LibraryLinkValue>({
    libraryNodeId: node?.library_node_id ?? null,
    libraryNodeType: node?.library_node_id
      ? (node.library_plan_mode ? NodeType.PLAIN_PROMPT : node.node_type)
      : null,
    planMode: node?.library_plan_mode ?? false,
    arguments: node?.library_arguments ?? "",
  });

  const isPipeline = mode === "pipeline";
  const availableTypes = isPipeline ? PIPELINE_TYPES : LIBRARY_ALLOWED_TYPES;
  /** Тип своего содержимого; `null` — нода выполняет промт библиотеки. */
  const nodeType = formType === LIBRARY_PROMPT_TYPE ? null : formType;
  const effectiveType = nodeType ?? libraryLink.libraryNodeType;
  const withEffort = effectiveType !== null && EFFORT_TYPES.includes(effectiveType);
  const withGuide = nodeType === NodeType.PLAIN_PROMPT;

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

  function contentFields() {
    if (nodeType === null) return linkedContentPayload(libraryLink);
    return ownContentPayload(
      { nodeType, promptTemplate, commandInvocation, scriptLanguage, scriptContent, guideUrl },
      { isPipeline },
    );
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
      is_skipped: isPipeline ? isSkipped : false,
      reasoning_effort: withEffort ? effort : null,
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
        <Label htmlFor="node-name" required>Название</Label>
        <Input id="node-name" value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      {!isPipeline && (nodeType === NodeType.PLAIN_PROMPT || nodeType === NodeType.SCRIPT) && <>
        <div><Label htmlFor="node-slash-name">Slash-команда</Label>
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
        <Label htmlFor="node-description" required={mode === "library"}>
          Описание
        </Label>
        <Textarea
          id="node-description"
          rows={2}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>
      <NodeTypeField value={formType} types={availableTypes} onChange={setFormType} />

      {nodeType === null ? (
        <LibraryPromptFields
          ownerId={pipelineOwnerId ?? node?.created_by}
          value={libraryLink}
          onChange={setLibraryLink}
        />
      ) : <>
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

        {withGuide && <NodeGuideField value={guideUrl} onChange={setGuideUrl} />}
      </>}

      {withEffort && (
        <NodeEffortField id="node-effort" value={effort} onChange={setEffort} />
      )}

      {isPipeline && (
        <label className="flex min-h-11 items-center gap-2.5 text-body font-semibold">
          <Checkbox checked={!isSkipped} onCheckedChange={(checked) => setIsSkipped(checked !== true)} />
          Активна по умолчанию
        </label>
      )}

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
            (nodeType === null && !libraryLink.libraryNodeId) ||
            isPending
          }
        >
          Сохранить
        </Button>
      </DialogFooter>
    </div>
  );
}
