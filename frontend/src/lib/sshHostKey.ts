import type { SshHostKeyState } from "@/components/admin/gitCredentials.types";

/** Тело запроса: без правок ключ не передаётся, сброс — пустая строка (раздел 19.3). */
export function sshHostKeyBody(state: SshHostKeyState): { ssh_known_hosts?: string } {
  if (state.knownHosts.trim()) return { ssh_known_hosts: state.knownHosts };
  return state.reset ? { ssh_known_hosts: "" } : {};
}

/** Строка списка: отпечаток ключа Git-сервера или что он ещё не получен. */
export function sshHostKeySummary(fingerprints: string[]): string {
  return fingerprints.length ? `ключ хоста ${fingerprints.join(", ")}` : "ключ хоста ещё не получен";
}
