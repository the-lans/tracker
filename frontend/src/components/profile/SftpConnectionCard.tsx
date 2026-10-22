import { Copy } from "lucide-react";
import { Card, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/common/feedback/EmptyState";
import { LoadingState } from "@/components/common/feedback/LoadingState";
import { useProfile, useSftpConnection } from "@/hooks/useProfile";
import { copyText } from "@/lib/textExport";
import { formatDateTime } from "@/lib/utils";
import type { SftpConnection } from "@/lib/types";

const MOUNT_DIR = "~/tracker";

function mountCommand(connection: SftpConnection, username: string): string {
  return `sshfs -p ${connection.port} ${username}@${connection.host}:/ ${MOUNT_DIR} -o reconnect`;
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex min-w-0 flex-wrap gap-x-2 text-small">
      <span className="text-text-3">{label}</span>
      <span className="min-w-0 font-mono [overflow-wrap:anywhere]">{value}</span>
    </div>
  );
}

/**
 * Раздел 15.1: подключение к файлам задач по SFTP — как к диску (sshfs,
 * SSHFS-Win, Mountain Duck). Видны свои задачи: `repos` только для чтения,
 * `artifacts` — для чтения и записи.
 */
export function SftpConnectionCard() {
  const { data: connection, isLoading } = useSftpConnection();
  const { data: profile } = useProfile();

  return (
    <Card>
      <CardTitle>Доступ к файлам задач (SFTP)</CardTitle>
      {isLoading && <LoadingState />}
      {connection && !connection.username && (
        <EmptyState
          compact
          title="Логин не назначен"
          hint="Логин для SFTP назначает администратор в разделе «Пользователи»."
        />
      )}
      {connection?.username && (
        <div className="flex flex-col gap-1.5">
          <Field label="Сервер" value={`${connection.host}:${connection.port}`} />
          <Field label="Логин" value={connection.username} />
          <Field
            label="Отпечаток сервера"
            value={connection.host_key_fingerprint ?? "появится после первого запуска шлюза"}
          />
          <Field
            label="Последний вход"
            value={formatDateTime(profile?.ssh_key_last_used_at)}
          />
          <div className="mt-1 flex min-w-0 items-center gap-1 rounded-md bg-surface-2 px-2 py-1.5">
            <code className="min-w-0 flex-1 font-mono text-small [overflow-wrap:anywhere]">
              {mountCommand(connection, connection.username)}
            </code>
            <button
              type="button"
              className="touch-target flex shrink-0 items-center justify-center hover:text-accent"
              aria-label="Копировать команду подключения"
              title="Копировать"
              onClick={() => copyText(mountCommand(connection, connection.username ?? ""))}
            >
              <Copy className="size-3.5" />
            </button>
          </div>
          <div className="text-small text-text-3">
            Вход — по SSH-ключу выше. Каталог задачи: <code className="font-mono">repos</code> —
            только чтение, <code className="font-mono">artifacts</code> — чтение и запись.
          </div>
        </div>
      )}
    </Card>
  );
}
