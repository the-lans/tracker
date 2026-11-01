import { useEffect, useState } from "react";
import { ExternalLink } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  useCancelLlmLogin,
  useLlmLoginStatus,
  useStartLlmLogin,
  useSubmitLlmLogin,
} from "@/hooks/useLlmAccounts";
import { errorMessage } from "@/lib/errors";
import { LlmLoginState, type LlmAccount, type LlmLoginStatus } from "@/lib/types";

/**
 * Раздел 19.7: вход в аккаунт через LLM-прокси. Трекер выдаёт ссылку OAuth,
 * пользователь входит у провайдера и вставляет адрес, на который браузер
 * перешёл после входа; пока прокси обменивает код, статус опрашивается.
 */
export function LlmAccountLoginDialog({
  account,
  onClose,
}: {
  account: LlmAccount;
  onClose: () => void;
}) {
  const start = useStartLlmLogin(account.id);
  const submit = useSubmitLlmLogin(account.id);
  const cancel = useCancelLlmLogin(account.id);
  const [redirectUrl, setRedirectUrl] = useState("");
  const [result, setResult] = useState<LlmLoginStatus | null>(null);
  const waiting = result?.state === LlmLoginState.WAIT;
  const { data: polled } = useLlmLoginStatus(account.id, waiting);
  const status = waiting && polled ? polled : result;
  const startLogin = start.mutate;

  useEffect(() => {
    startLogin(undefined, {
      onError: (error) => toast.error(errorMessage(error, "Не удалось начать вход")),
    });
  }, [startLogin]);

  useEffect(() => {
    if (status?.state === LlmLoginState.OK) {
      toast.success(`Вход в «${account.label}» выполнен`);
      onClose();
    }
  }, [status?.state, account.label, onClose]);

  function handleSubmit() {
    submit.mutate(redirectUrl.trim(), {
      onSuccess: setResult,
      onError: (error) => toast.error(errorMessage(error, "Не удалось завершить вход")),
    });
  }

  function handleCancel() {
    cancel.mutate(undefined, { onSettled: onClose });
  }

  return (
    <Dialog open onOpenChange={(open) => !open && handleCancel()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Вход в «{account.label}»</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <ol className="list-decimal pl-5 text-body text-text-2">
            <li>Откройте ссылку и войдите в аккаунт провайдера.</li>
            <li>
              После входа браузер перейдёт на адрес, который не откроется, — скопируйте его из
              адресной строки и вставьте ниже.
            </li>
          </ol>
          {start.data ? (
            <a
              href={start.data.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 self-start font-bold text-accent"
            >
              <ExternalLink className="size-4" /> Открыть страницу входа
            </a>
          ) : (
            <span className="text-meta text-text-3">Получаем ссылку входа…</span>
          )}
          <div>
            <Label htmlFor="llm-redirect">Адрес после входа</Label>
            <Input
              id="llm-redirect"
              placeholder="http://localhost:…/callback?code=…"
              value={redirectUrl}
              onChange={(e) => setRedirectUrl(e.target.value)}
            />
          </div>
          {waiting && <p className="text-meta text-text-3">Прокси завершает вход…</p>}
          {status?.state === LlmLoginState.ERROR && (
            <p role="alert" className="text-meta text-danger-text">
              {status.error ?? "Вход не удался"} — начните вход заново.
            </p>
          )}
        </div>
        <DialogFooter>
          <Button variant="secondary" onClick={handleCancel}>
            Отмена
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={!start.data || !redirectUrl.trim() || submit.isPending || waiting}
          >
            Завершить вход
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
