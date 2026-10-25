import { useState } from "react";
import { FileStack, Plus } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { TemplateForm } from "@/components/templates/TemplateForm";
import { useDeleteTemplate, useTemplates } from "@/hooks/useTemplates";
import { errorMessage } from "@/lib/errors";
import type { Template } from "@/lib/types";
import { ConfirmDeleteButton } from "@/components/common/actions/ConfirmDeleteButton";
import { EditButton } from "@/components/common/actions/EditButton";
import { OwnerLabel } from "@/components/common/avatar/OwnerLabel";
import { EmptyState } from "@/components/common/feedback/EmptyState";
import { PAGE_BODY, PAGE_ROOT } from "@/styles/classes";
import { LoadingState } from "@/components/common/feedback/LoadingState";
import { plural } from "@/lib/utils";
import { EntityFormDialog, type EditTarget } from "@/components/common/dialogs/EntityFormDialog";

function fileCountLabel(count: number): string {
  return `${count} ${plural(count, ["файл", "файла", "файлов"])}`;
}

export function TemplatesPage() {
  const { data: templates, isLoading } = useTemplates();
  const deleteTemplate = useDeleteTemplate();
  const [dialogTemplate, setDialogTemplate] = useState<EditTarget<Template>>(null);

  return (
    <div className={PAGE_ROOT}>
      <PageHeader
        title="Шаблоны"
        actions={
          <Button onClick={() => setDialogTemplate("new")}>
            <Plus className="size-4" /> Шаблон
          </Button>
        }
      />
      <div className={PAGE_BODY}>
        {isLoading && <LoadingState />}
        {!isLoading && (templates ?? []).length === 0 && (
          <EmptyState
            icon={FileStack}
            title="Шаблонов пока нет"
            hint="Шаблон — набор файлов (например, CLAUDE.md или .mcp.json) и MCP-серверов, которые подключаются к репозиторию задачи. Нажмите «+ Шаблон» вверху справа и добавьте файлы."
          />
        )}
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {(templates ?? []).map((template) => (
            <Card key={template.id} className="flex flex-col gap-1.5">
              <div className="flex items-center gap-1">
                <div className="min-w-0 flex-1 truncate font-bold" title={template.name}>
                  {template.name}
                </div>
                <EditButton name={template.name} onClick={() => setDialogTemplate(template)} />
                <ConfirmDeleteButton
                  kind="шаблон"
                  name={template.name}
                  pending={deleteTemplate.isPending}
                  onConfirm={() =>
                    deleteTemplate.mutate(template.id, {
                      onError: (error) =>
                        toast.error(
                          errorMessage(error, "Не удалось удалить"),
                        ),
                    })}
                />
              </div>
              <div className="text-small text-text-3">
                {fileCountLabel(Object.keys(template.files).length)}
              </div>
              <OwnerLabel ownerId={template.created_by} />
            </Card>
          ))}
        </div>
      </div>

      <EntityFormDialog
        target={dialogTemplate}
        onClose={() => setDialogTemplate(null)}
        createTitle="Новый шаблон"
        editTitle="Редактировать шаблон"
        contentClassName="max-w-2xl"
      >
        {(item, close) => (
          <TemplateForm
            template={item}
            onSaved={close}
            onCancel={close}
          />
        )}
      </EntityFormDialog>
    </div>
  );
}
