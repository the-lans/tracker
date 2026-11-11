import { useState } from "react";
import { toast } from "sonner";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { useTemplatePreview } from "@/hooks/useTemplates";
import { errorMessage } from "@/lib/errors";
import type { TemplatePreviewRequest } from "@/lib/types";

/**
 * Раздел 5.1: текст промта с подсказкой переменных и предпросмотром рендеринга.
 * У команды библиотеки (`argumentHint` не `undefined`) предпросмотр подставляет
 * аргументы из поля «Аргументы для предпросмотра»: `$1` — первый.
 */
export function PromptTemplateField({
  value,
  onChange,
  allowNodeVariables,
  previewRequest,
  argumentHint,
}: {
  value: string;
  onChange: (value: string) => void;
  allowNodeVariables: boolean;
  previewRequest: () => TemplatePreviewRequest;
  argumentHint?: string;
}) {
  const preview = useTemplatePreview();
  const [previewText, setPreviewText] = useState<string | null>(null);
  const [previewArguments, setPreviewArguments] = useState("");
  const withArguments = argumentHint !== undefined;

  function handlePreview() {
    const request = previewRequest();
    preview.mutate(withArguments ? { ...request, arguments: previewArguments } : request, {
      onSuccess: (data) => setPreviewText(data.rendered_text),
      onError: (error) => {
        toast.error(errorMessage(error, "Ошибка предпросмотра"));
        setPreviewText(null);
      },
    });
  }

  return (
    <div>
      <Label htmlFor="node-prompt">Текст промта</Label>
      <Textarea
        id="node-prompt"
        rows={5}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      <div className="mt-1 text-caption text-text-3">
        Доступные переменные: {"{{task.*}}"}, {"{{env.VAR}}"}
        {allowNodeVariables && ", {{node.*}}"}, {"{{session.id}}"}
      </div>
      {withArguments && (
        <div className="mt-1.5">
          <Label htmlFor="node-preview-arguments">Аргументы для предпросмотра</Label>
          <Input
            id="node-preview-arguments"
            placeholder={argumentHint || "сервис \"что проверить\""}
            value={previewArguments}
            onChange={(e) => setPreviewArguments(e.target.value)}
          />
        </div>
      )}
      <div className="mt-1.5 flex items-center gap-2">
        <Button type="button" size="sm" variant="secondary" onClick={handlePreview}>
          Предпросмотр
        </Button>
        {preview.isPending && <span className="text-caption text-text-3">Рендеринг…</span>}
      </div>
      {previewText !== null && (
        <div className="mt-2 whitespace-pre-wrap rounded-md border border-border bg-surface-2 p-2.5 text-note">
          {previewText}
        </div>
      )}
    </div>
  );
}
