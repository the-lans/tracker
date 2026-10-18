import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useCreateLlmAccount, useDeleteLlmAccount, useLlmAccounts } from "@/hooks/useLlmAccounts";
import { ApiError } from "@/lib/apiClient";
import { LlmAccountStatus } from "@/lib/types";

const STATUS_TONE: Record<LlmAccountStatus, "success" | "warning" | "danger"> = {
  [LlmAccountStatus.ACTIVE]: "success",
  [LlmAccountStatus.RATE_LIMITED]: "warning",
  [LlmAccountStatus.DISABLED]: "danger",
};

export function LlmAccountsPage() {
  const { data: accounts, isLoading } = useLlmAccounts();
  const createAccount = useCreateLlmAccount();
  const deleteAccount = useDeleteLlmAccount();
  const [open, setOpen] = useState(false);
  const [label, setLabel] = useState("");
  const [configDir, setConfigDir] = useState("");

  function handleCreate() {
    createAccount.mutate(
      { label, claude_config_dir: configDir },
      {
        onSuccess: () => {
          setOpen(false);
          setLabel("");
          setConfigDir("");
        },
        onError: (error) => {
          toast.error(error instanceof ApiError ? error.message : "Не удалось создать аккаунт");
        },
      },
    );
  }

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="LLM-аккаунты"
        actions={
          <Button onClick={() => setOpen(true)}>
            <Plus className="size-4" /> Аккаунт
          </Button>
        }
      />
      <div className="min-h-0 flex-1 overflow-auto px-5 pb-8 lg:px-8">
        {isLoading && <div className="text-text-3">Загрузка…</div>}
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {(accounts ?? []).map((account) => (
            <Card key={account.id} className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between">
                <div className="font-bold">{account.label}</div>
                <button
                  type="button"
                  onClick={() =>
                    deleteAccount.mutate(account.id, {
                      onError: (error) =>
                        toast.error(
                          error instanceof ApiError ? error.message : "Не удалось удалить",
                        ),
                    })
                  }
                  className="touch-target flex items-center justify-center text-text-3 hover:text-danger"
                  aria-label="Удалить"
                >
                  <Trash2 className="size-4" />
                </button>
              </div>
              <div className="truncate font-mono text-[12px] text-text-3">
                {account.claude_config_dir}
              </div>
              <Badge tone={STATUS_TONE[account.status]} className="self-start">
                {account.status}
              </Badge>
            </Card>
          ))}
        </div>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Новый LLM-аккаунт</DialogTitle>
          </DialogHeader>
          <div className="flex flex-col gap-3">
            <div>
              <Label htmlFor="llm-label">Название</Label>
              <Input id="llm-label" value={label} onChange={(e) => setLabel(e.target.value)} />
            </div>
            <div>
              <Label htmlFor="llm-dir">Путь к claude_config_dir</Label>
              <Input
                id="llm-dir"
                placeholder="/home/svc-claude-1/.claude"
                value={configDir}
                onChange={(e) => setConfigDir(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setOpen(false)}>
              Отмена
            </Button>
            <Button onClick={handleCreate} disabled={!label || !configDir || createAccount.isPending}>
              Создать
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
