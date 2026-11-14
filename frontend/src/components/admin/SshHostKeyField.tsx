import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import type { SshHostKeyState } from "@/components/admin/gitCredentials.types";

/**
 * Раздел 19.3: ключ Git-сервера для SSH. Пусто — запомнится при первом
 * подключении; при смене ключа на сервере сохранённый сбрасывают здесь.
 */
export function SshHostKeyField({
  fingerprints,
  value,
  onChange,
}: {
  fingerprints: string[];
  value: SshHostKeyState;
  onChange: (value: SshHostKeyState) => void;
}) {
  const saved = fingerprints.length > 0 && !value.reset;
  return (
    <div>
      <Label htmlFor="git-access-known-hosts">Ключ хоста (known_hosts)</Label>
      <textarea
        id="git-access-known-hosts"
        className="w-full rounded-md border border-border bg-surface p-2 font-mono text-small"
        rows={3}
        spellCheck={false}
        value={value.knownHosts}
        placeholder="git.example.com ssh-ed25519 AAAA…"
        onChange={(e) => onChange({ ...value, knownHosts: e.target.value })}
      />
      <p className="text-small text-text-3">
        {saved
          ? `Сохранён: ${fingerprints.join(", ")}. Вставьте строки, чтобы заменить.`
          : "Необязательно: пустое поле — ключ запомнится при первом подключении, отпечаток появится здесь."}
      </p>
      {fingerprints.length > 0 && (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => onChange({ knownHosts: "", reset: !value.reset })}
        >
          {value.reset ? "Не сбрасывать ключ хоста" : "Сбросить ключ хоста"}
        </Button>
      )}
      {value.reset && (
        <p className="text-small text-text-3">
          Ключ сбросится при сохранении и запомнится заново при следующем подключении.
        </p>
      )}
    </div>
  );
}
