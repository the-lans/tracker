import { useState } from "react";
import { toast } from "sonner";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { DialogFooter } from "@/components/ui/dialog";
import { useCreateNode, useUpdateNode } from "@/hooks/useNodes";
import { useTemplatePreview } from "@/hooks/useTemplates";
import { ApiError } from "@/lib/apiClient";
import { NodeType, ScriptLanguage, type NodeItem } from "@/lib/types";
import { NODE_TYPE_LABEL } from "@/components/tasks/NodeTypeIcon";

const PIPELINE_ONLY_TYPES = Object.values(NodeType);
const LIBRARY_ALLOWED_TYPES = [NodeType.PLAIN_PROMPT, NodeType.SLASH_COMMAND, NodeType.SCRIPT];

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
  const preview = useTemplatePreview();

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
  const [timeoutSeconds, setTimeoutSeconds] = useState(node?.timeout_seconds ?? 600);
  const [maxRetries, setMaxRetries] = useState(node?.max_retries ?? 3);
  const [isSkipped, setIsSkipped] = useState(node?.is_skipped ?? false);
  const [previewText, setPreviewText] = useState<string | null>(null);

  const availableTypes = mode === "pipeline" ? PIPELINE_ONLY_TYPES : LIBRARY_ALLOWED_TYPES;

  function handlePreview() {
    preview.mutate(
      {
        text: promptTemplate,
        scope: mode === "pipeline" ? "pipeline" : "library",
      },
      {
        onSuccess: (data) => setPreviewText(data.rendered_text),
        onError: (error) => {
          toast.error(error instanceof ApiError ? error.message : "Ошибка предпросмотра");
          setPreviewText(null);
        },
      },
    );
  }

  function handleSave() {
    const body = {
      pipeline_id: mode === "pipeline" ? pipelineId : null,
      order_index: mode === "pipeline" ? (orderIndex ?? node?.order_index ?? 0) : null,
      name,
      description: description || null,
      node_type: nodeType,
      prompt_template:
        nodeType === NodeType.PLAIN_PROMPT || nodeType === NodeType.PLAN_PROMPT
          ? promptTemplate
          : null,
      command_invocation: nodeType === NodeType.SLASH_COMMAND ? commandInvocation : null,
      script_language: nodeType === NodeType.SCRIPT ? scriptLanguage : null,
      script_content: nodeType === NodeType.SCRIPT ? scriptContent : null,
      guide_url: guideUrl || null,
      timeout_seconds: timeoutSeconds,
      max_retries: mode === "pipeline" ? maxRetries : 3,
      is_skipped: mode === "pipeline" ? isSkipped : false,
    };

    const onError = (error: unknown) => {
      toast.error(error instanceof ApiError ? error.message : "Не удалось сохранить ноду");
    };

    if (node) {
      updateNode.mutate(body, { onSuccess: onSaved, onError });
    } else {
      createNode.mutate(body, { onSuccess: onSaved, onError });
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
        <Label>Тип ноды</Label>
        <Select value={nodeType} onValueChange={(v) => setNodeType(v as NodeType)}>
          <SelectTrigger>
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
        <div className="rounded-md border border-info-tint bg-info-tint px-3 py-2 text-[12.5px] text-info-text">
          Нода доступна только внутри пайплайна и не может быть сохранена как элемент библиотеки.
        </div>
      )}

      {(nodeType === NodeType.PLAIN_PROMPT || nodeType === NodeType.PLAN_PROMPT) && (
        <div>
          <Label htmlFor="node-prompt">Текст промта</Label>
          <Textarea
            id="node-prompt"
            rows={5}
            value={promptTemplate}
            onChange={(e) => setPromptTemplate(e.target.value)}
          />
          <div className="mt-1 text-[11px] text-text-3">
            Доступные переменные: {"{{task.*}}"}, {"{{env.VAR}}"}
            {mode === "pipeline" && ", {{node.*}}"}, {"{{session.id}}"}
          </div>
          <div className="mt-1.5 flex items-center gap-2">
            <Button type="button" size="sm" variant="secondary" onClick={handlePreview}>
              Предпросмотр
            </Button>
            {preview.isPending && <span className="text-[11px] text-text-3">Рендеринг…</span>}
          </div>
          {previewText !== null && (
            <div className="mt-2 whitespace-pre-wrap rounded-md border border-border bg-surface-2 p-2.5 text-[12.5px]">
              {previewText}
            </div>
          )}
        </div>
      )}

      {nodeType === NodeType.SLASH_COMMAND && (
        <div>
          <Label htmlFor="node-command">Слэш-команда</Label>
          <Input
            id="node-command"
            placeholder="/code-review ultra"
            value={commandInvocation}
            onChange={(e) => setCommandInvocation(e.target.value)}
          />
          <div className="mt-1 text-[11px] text-text-3">
            Команда передаётся в сессию без изменений — шаблонизатор не применяется.
          </div>
        </div>
      )}

      {nodeType === NodeType.SCRIPT && (
        <>
          <div>
            <Label>Язык</Label>
            <Select value={scriptLanguage} onValueChange={(v) => setScriptLanguage(v as ScriptLanguage)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ScriptLanguage.PYTHON}>python</SelectItem>
                <SelectItem value={ScriptLanguage.BASH}>bash</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label htmlFor="node-script">Содержимое скрипта</Label>
            <Textarea
              id="node-script"
              rows={6}
              className="font-mono text-[12px]"
              value={scriptContent}
              onChange={(e) => setScriptContent(e.target.value)}
            />
          </div>
        </>
      )}

      <div>
        <Label htmlFor="node-guide">Гайд (URL Confluence)</Label>
        <Input id="node-guide" value={guideUrl} onChange={(e) => setGuideUrl(e.target.value)} />
      </div>

      <div>
        <Label htmlFor="node-timeout">Таймаут (сек.)</Label>
        <Input
          id="node-timeout"
          type="number"
          value={timeoutSeconds}
          onChange={(e) => setTimeoutSeconds(Number(e.target.value))}
        />
      </div>

      {mode === "pipeline" && (
        <>
          <div>
            <Label htmlFor="node-retries">Максимум попыток (retry)</Label>
            <Input
              id="node-retries"
              type="number"
              value={maxRetries}
              onChange={(e) => setMaxRetries(Number(e.target.value))}
            />
          </div>
          <label className="flex items-center gap-2 text-[13px] font-semibold">
            <input
              type="checkbox"
              checked={isSkipped}
              onChange={(e) => setIsSkipped(e.target.checked)}
            />
            Пропускать по умолчанию (is_skipped)
          </label>
        </>
      )}

      <DialogFooter>
        <Button type="button" variant="secondary" onClick={onCancel}>
          Отмена
        </Button>
        <Button type="button" onClick={handleSave} disabled={!name || isPending}>
          Сохранить
        </Button>
      </DialogFooter>
    </div>
  );
}
