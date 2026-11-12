import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { GitCredentialKind, GitlabApiState } from "@/components/admin/gitCredentials.types";

/** Раздел 16.2: опрос статуса MR через GitLab API с этими учётными данными. */
export function GitlabApiFields({
  kind,
  host,
  tokenSet,
  value,
  onChange,
}: {
  kind: GitCredentialKind;
  host: string;
  tokenSet: boolean;
  value: GitlabApiState;
  onChange: (patch: Partial<GitlabApiState>) => void;
}) {
  const ownToken = kind === "ssh_key" || !value.sameToken;
  return (
    <fieldset className="flex flex-col gap-2 rounded-md border border-border p-3">
      <legend className="px-1 text-small font-bold">GitLab API</legend>
      <label className="flex items-center gap-2 text-body">
        <Checkbox
          checked={value.enabled}
          onCheckedChange={(checked) => onChange({ enabled: checked === true })}
        />
        Статус MR через GitLab API
      </label>
      {value.enabled && (
        <>
          {kind === "https_token" && (
            <label className="flex items-center gap-2 text-body">
              <Checkbox
                checked={value.sameToken}
                onCheckedChange={(checked) => onChange({ sameToken: checked === true })}
              />
              Тот же токен, что для Git
            </label>
          )}
          {ownToken && (
            <div>
              <Label htmlFor="git-access-api-token" required={!tokenSet}>Токен GitLab API</Label>
              <Input
                id="git-access-api-token"
                type="password"
                autoComplete="new-password"
                placeholder={tokenSet ? "Сохранён — ввод заменит" : ""}
                value={value.token}
                onChange={(event) => onChange({ token: event.target.value })}
              />
              <p className="text-small text-text-3">Достаточно права read_api.</p>
            </div>
          )}
          <div>
            <Label htmlFor="git-access-api-url">Адрес GitLab</Label>
            <Input
              id="git-access-api-url"
              type="url"
              placeholder={`https://${host.trim() || "gitlab.example.com"}`}
              value={value.url}
              onChange={(event) => onChange({ url: event.target.value })}
            />
            <p className="text-small text-text-3">
              Если GitLab не на https://{host.trim() || "<хост>"}: свой порт или подкаталог.
            </p>
          </div>
        </>
      )}
    </fieldset>
  );
}
