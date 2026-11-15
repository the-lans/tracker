import { ExternalLink } from "lucide-react";
import { useJiraServer } from "@/hooks/useProfile";
import type { Task } from "@/lib/types";

/** Ссылка импортированной задачи или ссылка по коду и адресу Jira из настроек. */
export function TaskJiraLink({ task }: { task: Task }) {
  const { data: server } = useJiraServer();
  const href = task.jira_issue_url ?? (
    server?.jira_url && /^[A-Za-z][A-Za-z0-9_]*-\d+$/.test(task.code)
      ? `${server.jira_url.replace(/\/+$/, "")}/browse/${task.code}`
      : null
  );
  if (!href) return null;

  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      aria-label="Открыть задачу в Jira"
      title="Открыть задачу в Jira"
      className="touch-target inline-flex size-8 shrink-0 items-center justify-center rounded-lg text-text-3 hover:bg-info-tint hover:text-info-text"
    >
      <ExternalLink className="size-4" />
    </a>
  );
}
