import { GitBranch } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useRemoteDefaultBranch } from "@/hooks/useRepositories";
import { toastError } from "@/lib/errors";

/**
 * Раздел 3.1: ветка по умолчанию репозитория — её форма задачи подставляет
 * базовой веткой. Кнопка справа берёт ветку HEAD git-сервера по адресу и
 * учётным данным, введённым в форме.
 */
export function RepositoryBranchField({
  value,
  onChange,
  gitUrl,
  credentialId,
}: {
  value: string;
  onChange: (value: string) => void;
  gitUrl: string;
  credentialId: string | null;
}) {
  const remoteBranch = useRemoteDefaultBranch();

  function fillFromServer() {
    remoteBranch.mutate(
      { git_url: gitUrl.trim(), git_credential_id: credentialId },
      {
        onSuccess: ({ default_branch }) => onChange(default_branch),
        onError: toastError("Не удалось получить ветку с git-сервера"),
      },
    );
  }

  return (
    <div>
      <Label htmlFor="repo-default-branch" required>Ветка по умолчанию</Label>
      <div className="flex gap-2">
        <Input
          id="repo-default-branch"
          placeholder="master"
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
        <Button
          type="button"
          variant="secondary"
          className="shrink-0"
          title="Взять ветку по умолчанию с git-сервера"
          aria-label="С сервера"
          disabled={!gitUrl.trim() || remoteBranch.isPending}
          onClick={fillFromServer}
        >
          {/* На узком экране — только иконка: поле ветки остаётся шире. */}
          <GitBranch /> <span className="hidden sm:inline">С сервера</span>
        </Button>
      </div>
      <p className="text-small text-text-3">Подставляется базовой веткой при выборе репозитория в задаче.</p>
    </div>
  );
}
