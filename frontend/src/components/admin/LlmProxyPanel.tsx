import { CircleCheck, CircleX, KeyRound } from "lucide-react";
import { Card } from "@/components/ui/card";
import { ProxyCredentialRow } from "@/components/admin/ProxyCredentialRow";
import { useLlmProxyState } from "@/hooks/useAdmin";
import type { ProxyState } from "@/lib/types";
import { EmptyState } from "@/components/common/feedback/EmptyState";
import { LoadingState } from "@/components/common/feedback/LoadingState";
import { SectionTitle } from "@/components/common/typography/SectionTitle";

function ProxyStatusCard({ state }: { state: ProxyState }) {
  const outdated = state.latest_version !== null && state.latest_version !== state.version;
  return (
    <Card className="flex items-start gap-3">
      {state.available ? (
        <CircleCheck className="mt-0.5 size-4 shrink-0 text-success" />
      ) : (
        <CircleX className="mt-0.5 size-4 shrink-0 text-danger" />
      )}
      <div className="min-w-0 flex-1 text-body">
        <div className="font-bold">
          {state.available ? "Прокси доступен" : "Прокси недоступен"}
        </div>
        {state.error && <div className="text-meta text-danger-text">{state.error}</div>}
        <div className="text-meta text-text-2">
          Версия {state.version}
          {state.latest_version && `, последняя выпущенная — ${state.latest_version}`}
        </div>
        {outdated && (
          <div className="text-meta text-text-3">
            Обновление версии — через <code className="font-mono">deploy/install.sh --update</code>.
          </div>
        )}
      </div>
    </Card>
  );
}

/** Раздел 15.5: состояние LLM-прокси и все его учётки. */
export function LlmProxyPanel() {
  const { data: state, isLoading } = useLlmProxyState();

  return (
    <div className="flex flex-col gap-2">
      <SectionTitle>LLM-прокси</SectionTitle>
      {isLoading && <LoadingState />}
      {state && <ProxyStatusCard state={state} />}
      {state?.available && state.credentials.length === 0 && (
        <EmptyState
          icon={KeyRound}
          title="Учёток в прокси пока нет"
          hint="Учётка появляется, когда пользователь входит в свой LLM-аккаунт в разделе «LLM-аккаунты»."
        />
      )}
      {(state?.credentials ?? []).map((credential) => (
        <ProxyCredentialRow key={credential.name} credential={credential} />
      ))}
    </div>
  );
}
