import { useState } from "react";
import { toast } from "sonner";
import { Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { useTemplatePreview } from "@/hooks/useTemplates";
import { errorMessage } from "@/lib/errors";
import type { TemplatePreviewRequest } from "@/lib/types";

/** Раздел 5.1: текст промта с подсказкой переменных и предпросмотром рендеринга. */
export function PromptTemplateField({
  value,
  onChange,
  allowNodeVariables,
  previewRequest,
}: {
  value: string;
  onChange: (value: string) => void;
  allowNodeVariables: boolean;
  previewRequest: () => TemplatePreviewRequest;
}) {
  const preview = useTemplatePreview();
  const [previewText, setPreviewText] = useState<string | null>(null);

  function handlePreview() {
    preview.mutate(previewRequest(), {
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
