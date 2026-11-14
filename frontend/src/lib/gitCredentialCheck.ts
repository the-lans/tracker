/**
 * Итог «Проверить сохранённый доступ» (раздел 15.5): чтение Git, отпечаток
 * ключа хоста для сверки (раздел 19.3) и доступ к GitLab API.
 */

import type { GitCredentialCheck } from "@/components/admin/gitCredentials.types";
import { GITLAB_API_OK, gitlabApiCheckMessage } from "@/lib/gitlabApi";
import { sshHostKeySummary } from "@/lib/sshHostKey";

const READ_ACCESS_MESSAGE = "Чтение доступно. Право записи этой проверкой не проверяется.";

export interface GitCredentialCheckOutcome {
  message: string;
  /** Git читается, но API отклонён — ошибка настройки опроса статуса MR. */
  failed: boolean;
}

export function gitCredentialCheckOutcome(result: GitCredentialCheck): GitCredentialCheckOutcome {
  const hostKeyMessage = result.ssh_host_key_fingerprints.length
    ? ` Сверьте ${sshHostKeySummary(result.ssh_host_key_fingerprints)} с Git-сервером.`
    : "";
  const gitMessage = `${READ_ACCESS_MESSAGE}${hostKeyMessage}`;
  const apiMessage = gitlabApiCheckMessage(result.gitlab_api);
  return {
    message: apiMessage ? `${gitMessage} ${apiMessage}` : gitMessage,
    failed: Boolean(apiMessage) && result.gitlab_api !== GITLAB_API_OK,
  };
}
