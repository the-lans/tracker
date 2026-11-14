import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/input";
import { ConfirmActionButton } from "@/components/common/actions/ConfirmActionButton";
import { QueryState } from "@/components/common/feedback/QueryState";
import {
  useDailyTemplate,
  usePreviewDailyTemplate,
  useResetDailyTemplate,
  useSaveDailyTemplate,
} from "@/hooks/useDaily";
import type { DailyTemplate } from "@/lib/daily.types";
import { toastError } from "@/lib/errors";

/** Лимит `DailyTemplateRequest` (`services/daily_plans.MAX_DAILY_TEXT_LENGTH`). */
const MAX_TEMPLATE_LENGTH = 20000;

/** Что подставляет каждая переменная `{{daily.*}}` (`services/daily_plans.py`). */
const DAILY_VARIABLE_HINT: Record<string, string> = {
  "daily.date": "дата плана",
  "daily.previous_date": "дата прошлого дня с отметками или событиями",
  "daily.yesterday": "сделанные задачи прошлого дня, затем его события",
  "daily.today": "события дня, затем отмеченные задачи",
  "daily.done": "задачи прошлого дня, по которым была работа",
  "daily.planned": "задачи, отмеченные на день",
  "daily.events": "события дня",
  "daily.previous_events": "события прошлого дня",
};

function TemplateEditor({ template }: { template: DailyTemplate }) {
  const [draft, setDraft] = useState(template.content);
  const saveTemplate = useSaveDailyTemplate();
  const resetTemplate = useResetDailyTemplate();
  const preview = usePreviewDailyTemplate();
  const changed = draft !== template.content;

  return (
    <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
      <Card className="flex min-w-0 flex-col gap-3">
        <CardTitle className="mb-0">
          Шаблон плана{template.is_default && <span className="font-normal text-text-3">по умолчанию</span>}
        </CardTitle>
        <Textarea
          aria-label="Текст шаблона"
          rows={12}
          maxLength={MAX_TEMPLATE_LENGTH}
          className="font-mono text-small"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
        <div className="flex flex-wrap gap-2">
          <Button
            disabled={!changed || !draft.trim() || saveTemplate.isPending}
            onClick={() =>
              saveTemplate.mutate(draft, {
                onSuccess: () => toast.success("Шаблон сохранён"),
                onError: toastError("Не удалось сохранить шаблон"),
              })}
          >
            Сохранить
          </Button>
          <Button
            variant="secondary"
            disabled={!draft.trim() || preview.isPending}
            onClick={() => preview.mutate(draft, { onError: toastError("Не удалось собрать предпросмотр") })}
          >
            Предпросмотр
          </Button>
          <ConfirmActionButton
            variant="ghost"
            title="Сбросить шаблон?"
            description="Свой шаблон удалится, новые планы будут собираться по шаблону по умолчанию. Уже созданные планы не меняются."
            confirmLabel="Сбросить"
            disabled={template.is_default}
            pending={resetTemplate.isPending}
            onConfirm={() => resetTemplate.mutate(undefined, { onError: toastError("Не удалось сбросить шаблон") })}
          >
            Сбросить к шаблону по умолчанию
          </ConfirmActionButton>
        </div>
        <div>
          <div className="mb-1 text-small font-bold text-text-2">Переменные</div>
          <ul className="flex flex-col gap-0.5 text-small text-text-3">
            {template.variables.map((variable) => (
              <li key={variable} className="break-words">
                <code className="font-mono text-text-2">{`{{${variable}}}`}</code>
                {DAILY_VARIABLE_HINT[variable] && ` — ${DAILY_VARIABLE_HINT[variable]}`}
              </li>
            ))}
          </ul>
        </div>
      </Card>
      <Card className="min-w-0">
        <CardTitle>Предпросмотр на сегодня</CardTitle>
        {preview.data ? (
          <pre className="whitespace-pre-wrap break-words font-mono text-small text-text">{preview.data.content}</pre>
        ) : (
          <div className="text-small text-text-3">
            Нажмите «Предпросмотр» — шаблон соберётся по отметкам и событиям, без сохранения.
          </div>
        )}
      </Card>
    </div>
  );
}

/** Раздел 15.8: «Шаблоны» — свой шаблон плана на день с переменными `{{daily.*}}`. */
export function DailyTemplateTab() {
  const { data: template, isLoading, isError } = useDailyTemplate();

  return (
    <QueryState isLoading={isLoading} isError={isError} errorLabel="Не удалось загрузить шаблон">
      {template && (
        <TemplateEditor key={`${template.is_default}:${template.content}`} template={template} />
      )}
    </QueryState>
  );
}
