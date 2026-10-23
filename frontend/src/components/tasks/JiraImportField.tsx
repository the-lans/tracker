import { useState } from "react";
import { Link } from "react-router-dom";
import { Download } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useJiraIssueDraft, useProfile } from "@/hooks/useProfile";
import { ApiError } from "@/lib/apiClient";
import { formatFileSize } from "@/lib/utils";
import type { JiraIssueDraft } from "@/lib/types";

/**
 * Раздел 15.6: «Заполнить из Jira» — код, название и описание формы берутся
 * из задачи Jira; ссылка и вложения подставятся при создании задачи.
 */
export function JiraImportField({
  onImported,
}: {
  onImported: (draft: JiraIssueDraft) => void;
}) {
  const { data: profile } = useProfile();
  const fetchDraft = useJiraIssueDraft();
  const [key, setKey] = useState("");
  const [imported, setImported] = useState<JiraIssueDraft | null>(null);

  if (profile && !profile.jira_token_set) {
    return (
      <div className="text-meta text-text-3">
        Чтобы заполнять задачу из Jira, подключите Jira в{" "}
        <Link to="/profile" className="text-accent underline">
          профиле
        </Link>
        .
      </div>
    );
  }

  function handleImport() {
    fetchDraft.mutate(key, {
      onSuccess: (draft) => {
        setImported(draft);
        onImported(draft);
      },
      onError: (error) =>
        toast.error(error instanceof ApiError ? error.message : "Не удалось получить задачу Jira"),
    });
  }

  return (
    <div>
      <Label htmlFor="jira-key">Ключ задачи Jira</Label>
      <div className="flex flex-wrap gap-2">
        <Input
          id="jira-key"
          className="min-w-0 flex-1 basis-40"
          placeholder="PROJ-123"
          value={key}
          onChange={(event) => setKey(event.target.value)}
        />
        <Button
          type="button"
          variant="secondary"
          className="shrink-0"
          disabled={!key.trim() || fetchDraft.isPending}
          onClick={handleImport}
        >
          <Download className="size-4" /> Заполнить из Jira
        </Button>
      </div>
      {imported && (
        <div className="mt-1 text-meta text-text-3">
          Заполнено из{" "}
          <a href={imported.issue_url} target="_blank" rel="noreferrer" className="text-accent underline">
            {imported.code}
          </a>
          {imported.attachments.length > 0 &&
            `. Вложения скопируются в артефакты: ${imported.attachments
              .map((attachment) => `${attachment.filename} (${formatFileSize(attachment.size)})`)
              .join(", ")}`}
        </div>
      )}
    </div>
  );
}
