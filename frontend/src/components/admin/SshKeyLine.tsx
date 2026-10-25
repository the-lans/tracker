import { Copy, KeyRound } from "lucide-react";
import { copyText } from "@/lib/textExport";
import { formatDateTime } from "@/lib/utils";
import type { User } from "@/lib/types";

/** Раздел 15.1, 15.5: ключ SFTP пользователя и последний вход по нему. */
export function SshKeyLine({ user }: { user: User }) {
  if (user.ssh_public_key === null) {
    return <div className="text-meta text-text-3">SSH-ключ не добавлен</div>;
  }
  const publicKey = user.ssh_public_key;
  return (
    <div className="flex min-w-0 items-center gap-1 text-meta text-text-3">
      <KeyRound className="size-3.5 shrink-0" />
      <span className="truncate font-mono" title={publicKey}>
        {user.ssh_key_fingerprint}
      </span>
      <span className="shrink-0">· вход: {formatDateTime(user.ssh_key_last_used_at)}</span>
      <button
        type="button"
        className="touch-target flex shrink-0 items-center justify-center hover:text-accent"
        aria-label={`Копировать SSH-ключ ${user.email}`}
        title="Копировать ключ"
        onClick={() => copyText(publicKey)}
      >
        <Copy className="size-3.5" />
      </button>
    </div>
  );
}
