import { useCallback, useEffect, useState } from "react";
import { ExternalLink } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  useCancelLlmLogin,
  useLlmLoginStatus,
  useRefreshLlmAccounts,
  useStartLlmLogin,
  useSubmitLlmLogin,
} from "@/hooks/useLlmAccounts";
import { useSecondsLeft } from "@/hooks/useSecondsLeft";
import { errorMessage } from "@/lib/errors";
import { LlmLoginState, type LlmAccount, type LlmLoginStatus } from "@/lib/types";
import { formatCountdown } from "@/lib/utils";

const EXPIRED_MESSAGE = "Время входа истекло";

/**
 * Разделы 15.1, 19.5: вход в аккаунт через LLM-прокси. Трекер выдаёт ссылку
 * OAuth, пользователь входит у провайдера и вставляет адрес, на который
 * браузер перешёл после входа, пока прокси его ждёт (`expires_at`); пока
 * прокси обменивает код, статус опрашивается.
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
  const refreshAccounts = useRefreshLlmAccounts();
  const secondsLeft = useSecondsLeft(start.data?.expires_at);
  const startLogin = start.mutate;
  const failure =
    status?.state === LlmLoginState.ERROR
      ? (status.error ?? "Вход не удался")
      : secondsLeft === 0 && !waiting
        ? EXPIRED_MESSAGE
        : null;

  const beginLogin = useCallback(() => {
    startLogin(undefined, {
      onError: (error) => toast.error(errorMessage(error, "Не удалось начать вход")),
    });
  }, [startLogin]);

  useEffect(beginLogin, [beginLogin]);

  useEffect(() => {
    if (status?.state === LlmLoginState.OK) {
      refreshAccounts();
      toast.success(`Вход в «${account.label}» выполнен`);
      onClose();
    }
  }, [status?.state, account.label, onClose, refreshAccounts]);

  function handleRestart() {
    setResult(null);
    setRedirectUrl("");
    beginLogin();
  }

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
          {!start.data && (
            <span className="text-meta text-text-3">Получаем ссылку входа…</span>
          )}
          {start.data && !failure && (
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <a
                href={start.data.url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1.5 font-bold text-accent"
              >
                <ExternalLink className="size-4" /> Открыть страницу входа
              </a>
              {secondsLeft !== null && !waiting && (
                <span className="text-meta text-text-3">
                  Осталось {formatCountdown(secondsLeft)}
                </span>
              )}
            </div>
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
          {failure && (
            <p role="alert" className="text-meta text-danger-text">
              {failure} — начните вход заново.
            </p>
          )}
        </div>
        <DialogFooter>
          <Button variant="secondary" onClick={handleCancel}>
            Отмена
          </Button>
          {failure ? (
            <Button onClick={handleRestart} disabled={start.isPending}>
              Начать заново
            </Button>
          ) : (
            <Button
              onClick={handleSubmit}
              disabled={!start.data || !redirectUrl.trim() || submit.isPending || waiting}
            >
              Завершить вход
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
