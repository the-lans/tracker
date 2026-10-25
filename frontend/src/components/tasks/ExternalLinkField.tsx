import { ExternalLink } from "lucide-react";

/** Подписанная внешняя ссылка карточки задачи (гайд, задача Jira) — в новой вкладке. */
export function ExternalLinkField({
  label,
  href,
  text,
}: {
  label: string;
  href: string;
  text: string;
}) {
  return (
    <>
      <div className="mb-1 mt-2.5 text-meta font-bold text-text-3">{label}</div>
      <a
        href={href}
        target="_blank"
        rel="noreferrer"
        className="touch-target inline-flex items-center gap-1.5 rounded-lg bg-info-tint px-2.5 py-1.5 text-note font-bold text-info-text"
      >
        <ExternalLink className="size-3.5" />
        {text}
      </a>
    </>
  );
}
