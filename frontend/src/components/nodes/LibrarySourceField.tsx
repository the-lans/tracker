import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useNodes } from "@/hooks/useNodes";
import { NODE_TYPE_LABEL } from "@/lib/labels";
import { NodeType, type NodeItem } from "@/lib/types";
import {
  LINKABLE_NODE_TYPES,
  NodeSource,
  type LibrarySourceValue,
} from "@/components/nodes/nodeForm.types";

function contentOf(item: NodeItem): string {
  if (item.node_type === NodeType.SLASH_COMMAND) return item.command_invocation ?? "";
  if (item.node_type === NodeType.SCRIPT) return item.script_content ?? "";
  return item.prompt_template ?? "";
}

function itemTitle(item: NodeItem): string {
  return item.slash_name ? `${item.name} (/${item.slash_name})` : item.name;
}

/** Промт библиотеки, на который сослалась нода: описание и содержимое — только для чтения. */
function LibraryItemPreview({ item }: { item: NodeItem }) {
  return (
    <div className="flex flex-col gap-2 rounded-md border border-border bg-surface-2 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge>{NODE_TYPE_LABEL[item.node_type]}</Badge>
        {item.revision !== undefined && <span className="text-caption text-text-3">версия {item.revision}</span>}
        {item.is_archived && <Badge tone="warning">в архиве</Badge>}
      </div>
      {item.description && <div className="text-body text-text-2">{item.description}</div>}
      <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words font-mono text-small text-text">
        {contentOf(item)}
      </pre>
      {item.guide_url && (
        <a
          href={item.guide_url}
          target="_blank"
          rel="noreferrer"
          className="w-fit break-all text-small font-bold text-accent"
        >
          Гайд: {item.guide_url}
        </a>
      )}
    </div>
  );
}

/**
 * Раздел 7.6: источник содержимого ноды пайплайна — свой текст или промт
 * библиотеки автора пайплайна. Текст, скрипт и гайд нода со ссылкой берёт у
 * промта при каждом запуске, свои у неё — аргументы и параметры выполнения.
 */
export function LibrarySourceField({
  ownerId,
  value,
  onChange,
}: {
  ownerId: string | undefined;
  value: LibrarySourceValue;
  onChange: (value: LibrarySourceValue) => void;
}) {
  const { data: items } = useNodes({ libraryOnly: true, includeArchived: true });
  // Как у команд чата: библиотеки разных пользователей не смешиваются.
  const candidates = (items ?? []).filter(
    (item) =>
      item.created_by === ownerId &&
      LINKABLE_NODE_TYPES.includes(item.node_type) &&
      (!item.is_archived || item.id === value.libraryNodeId),
  );
  const selected = candidates.find((item) => item.id === value.libraryNodeId);

  return (
    <div className="flex flex-col gap-3">
      <div>
        <Label htmlFor="node-source">Содержимое ноды</Label>
        <Select
          value={value.source}
          onValueChange={(source) => onChange({ ...value, source: source as NodeSource })}
        >
          <SelectTrigger id="node-source">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NodeSource.OWN}>Свой текст</SelectItem>
            <SelectItem value={NodeSource.LIBRARY}>Промт из библиотеки</SelectItem>
          </SelectContent>
        </Select>
      </div>
      {value.source === NodeSource.LIBRARY && (
        <>
          <div>
            <Label htmlFor="node-library-item">Промт библиотеки</Label>
            <Select
              value={value.libraryNodeId ?? ""}
              onValueChange={(libraryNodeId) =>
                onChange({
                  ...value,
                  libraryNodeId,
                  libraryNodeType:
                    candidates.find((item) => item.id === libraryNodeId)?.node_type ?? null,
                })
              }
            >
              <SelectTrigger id="node-library-item">
                <SelectValue placeholder="Выберите промт" />
              </SelectTrigger>
              <SelectContent>
                {candidates.map((item) => (
                  <SelectItem key={item.id} value={item.id}>
                    {itemTitle(item)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {items && candidates.length === 0 && (
              <p className="mt-1 text-small text-text-3">
                В библиотеке автора пайплайна нет промтов, скриптов или слэш-команд.
              </p>
            )}
          </div>
          {selected && <LibraryItemPreview item={selected} />}
          <div>
            <Label htmlFor="node-library-arguments">Аргументы</Label>
            <Input
              id="node-library-arguments"
              placeholder={selected?.argument_hint ?? ""}
              value={value.arguments}
              onChange={(event) => onChange({ ...value, arguments: event.target.value })}
            />
            <p className="mt-1 text-small text-text-3">
              Как после /имя в чате: в промте — $ARGUMENTS и $1, $2…; слэш-команде — через
              пробел после неё; скрипту — позиционные аргументы и TRACKER_COMMAND_ARGUMENTS.
            </p>
          </div>
        </>
      )}
    </div>
  );
}
