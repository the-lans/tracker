import { useId, useRef, useState, type ChangeEvent } from "react";
import { FileUp, Trash2, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { readTemplateFile } from "@/lib/templateFiles";
import { cn, formatFileSize } from "@/lib/utils";
import type { TemplateFileRow } from "@/components/templates/templateForm.types";

const TEXT_ENCODER = new TextEncoder();

function sourceCaption(row: TemplateFileRow): string {
  if (row.fileName !== undefined && row.fileSize !== undefined) {
    return `${row.fileName} · ${formatFileSize(row.fileSize)}`;
  }
  if (row.content) {
    return `Текст из поля · ${formatFileSize(TEXT_ENCODER.encode(row.content).length)}`;
  }
  return "Файл не выбран";
}

/** Строка файла шаблона: путь и содержимое — текстом или из файла с диска (раздел 15.1). */
export function TemplateFileField({
  row,
  onChange,
  onRemove,
}: {
  row: TemplateFileRow;
  onChange: (patch: Partial<TemplateFileRow>) => void;
  onRemove: () => void;
}) {
  const id = useId();
  const errorId = `${id}-error`;
  const inputRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const pathLabel = row.path || "без пути";

  function toggleFromFile(fromFile: boolean) {
    setError(null);
    onChange({ fromFile });
  }

  async function handleFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    const result = await readTemplateFile(file);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    setError(null);
    onChange({
      content: result.content,
      fileName: result.name,
      fileSize: result.size,
      ...(row.path.trim() ? {} : { path: result.name }),
    });
  }

  return (
    <div className="flex flex-col gap-1 rounded-md border border-border p-2">
      <div className="flex items-center gap-1">
        <Input
          aria-label="Путь файла"
          placeholder=".claude/settings.json"
          value={row.path}
          onChange={(e) => onChange({ path: e.target.value })}
        />
        {/* Переключатель-иконка, а не галка с подписью: путь не сжимается на узком экране. */}
        <button
          type="button"
          aria-label="Из файла"
          aria-pressed={row.fromFile}
          title={row.fromFile ? "Вводить текстом" : "Загрузить содержимое из файла с диска"}
          onClick={() => toggleFromFile(!row.fromFile)}
          className={cn(
            "touch-target flex shrink-0 items-center justify-center rounded-md text-text-3 hover:text-text",
            row.fromFile && "bg-accent-tint text-accent hover:text-accent",
          )}
        >
          <FileUp className="size-4" />
        </button>
        <button
          type="button"
          aria-label={`Убрать файл ${pathLabel}`}
          onClick={onRemove}
          className="touch-target flex shrink-0 items-center justify-center text-text-3 hover:text-danger"
        >
          <Trash2 className="size-4" />
        </button>
      </div>
      {row.fromFile ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant="secondary"
            aria-describedby={error ? errorId : undefined}
            onClick={() => inputRef.current?.click()}
          >
            <Upload className="size-3.5" /> Выбрать файл
          </Button>
          <span className="min-w-0 truncate text-meta text-text-3">{sourceCaption(row)}</span>
          <input
            ref={inputRef}
            type="file"
            className="hidden"
            aria-label={`Файл для ${pathLabel}`}
            aria-describedby={error ? errorId : undefined}
            onChange={(event) => void handleFile(event)}
          />
        </div>
      ) : (
        <Textarea
          rows={3}
          aria-label="Содержимое файла"
          placeholder="Содержимое файла"
          value={row.content}
          // Правленный текст — уже не копия выбранного файла.
          onChange={(e) => onChange({ content: e.target.value, fileName: undefined, fileSize: undefined })}
        />
      )}
      {error && (
        <div id={errorId} role="alert" className="text-meta font-semibold text-danger-text">
          {error}
        </div>
      )}
    </div>
  );
}
