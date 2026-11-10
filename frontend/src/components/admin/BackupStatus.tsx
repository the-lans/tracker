import { Badge } from "@/components/ui/badge";
import { BACKUP_RUN_STATUS_LABEL, BACKUP_RUN_STATUS_TONE } from "@/lib/labels";
import type { BackupRun } from "@/lib/types";
import { formatDateTime, formatFileSize } from "@/lib/utils";

const SHOWN_SKIPPED_FILES = 5;

function objectName(key: string): string {
  return key.slice(key.lastIndexOf("/") + 1);
}

function RunLine({ title, run }: { title: string; run: BackupRun | null }) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="font-bold text-text">{title}</span>
        {run ? (
          <>
            <Badge tone={BACKUP_RUN_STATUS_TONE[run.status]}>
              {BACKUP_RUN_STATUS_LABEL[run.status]}
            </Badge>
            <span className="text-meta text-text-3">
              {formatDateTime(run.finished_at ?? run.started_at)}
            </span>
            {run.size_bytes !== null && (
              <span className="text-meta text-text-3">{formatFileSize(run.size_bytes)}</span>
            )}
          </>
        ) : (
          <span className="text-meta text-text-3">ещё не запускался</span>
        )}
      </div>
      {run?.object_key && (
        <div className="break-all font-mono text-meta text-text-3">{objectName(run.object_key)}</div>
      )}
      {run?.error_message && (
        <div className="break-words text-small text-danger-text">{run.error_message}</div>
      )}
      {run && run.skipped_files.length > 0 && (
        <div className="text-small text-warning-text">
          Пропущено файлов: {run.skipped_files.length} — заняты или менялись при чтении
          <ul className="mt-1 list-disc pl-5 break-all font-mono text-meta">
            {run.skipped_files.slice(0, SHOWN_SKIPPED_FILES).map((file) => (
              <li key={`${file.component}/${file.path}`}>
                {file.component}/{file.path}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/** Раздел 15.5, 20.4: итоги последнего бэкапа и последней проверки восстановления. */
export function BackupStatus({
  lastBackup,
  lastVerify,
}: {
  lastBackup: BackupRun | null;
  lastVerify: BackupRun | null;
}) {
  return (
    <div className="flex flex-col gap-3 border-t border-border pt-3">
      <RunLine title="Последний бэкап" run={lastBackup} />
      <RunLine title="Последняя проверка восстановления" run={lastVerify} />
      <div className="text-small text-text-3">
        Запустить вне расписания или изменить время — задачи «Резервное копирование в S3» и
        «Проверка восстановления из S3» на вкладке «Периодические задачи».
      </div>
    </div>
  );
}
