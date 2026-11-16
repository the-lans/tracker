import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ConfirmDeleteButton } from "@/components/common/actions/ConfirmDeleteButton";
import { QueryState } from "@/components/common/feedback/QueryState";
import { useDeleteTwg, useTwg, useUpdateTwg } from "@/hooks/useTwg";
import { toastError } from "@/lib/errors";
import type { TwgConnection } from "@/lib/twg.types";

function ConnectionForm({ connection }: { connection: TwgConnection }) {
  const [site, setSite] = useState(connection.site ?? "");
  const [email, setEmail] = useState(connection.email ?? "");
  const [token, setToken] = useState("");
  const save = useUpdateTwg();
  const remove = useDeleteTwg();

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate({ site: site.trim(), email: email.trim(), token: token || null }, {
      onSuccess: () => { setToken(""); toast.success("Подключение TWG сохранено"); },
      onError: toastError("Не удалось сохранить TWG"),
    });
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-3">
      <p className="text-small text-text-2">
        Поиск и изменение Jira и Confluence агентом от вашего имени, в пределах ваших прав.
        {connection.configured && " Данные подключения сохранены."}
      </p>
      <div>
        <Label htmlFor="twg-site" required>Сайт Atlassian</Label>
        <Input id="twg-site" required value={site} placeholder="company.atlassian.net"
          onChange={(event) => setSite(event.target.value)} />
      </div>
      <div>
        <Label htmlFor="twg-email" required>Email Atlassian</Label>
        <Input id="twg-email" type="email" required value={email}
          onChange={(event) => setEmail(event.target.value)} />
      </div>
      <div>
        <Label htmlFor="twg-token" required={!connection.configured}>Токен Atlassian для TWG</Label>
        <Input id="twg-token" type="password" autoComplete="off" value={token}
          required={!connection.configured} onChange={(event) => setToken(event.target.value)}
          placeholder={connection.configured ? "Сохранён — ввод заменит" : ""} />
        <p className="mt-1 text-meta text-text-3">
          Личный API-токен из настроек Atlassian хранится зашифрованным и не показывается.
          При смене сайта или email введите токен заново.
        </p>
      </div>
      <p className="text-meta text-text-3">
        Настройки применяются при новом запуске задачи. Уже работающие задачи используют прежние данные.
        Истёкший токен нужно заменить; сохранение не проверяет его действительность.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" disabled={save.isPending || remove.isPending}>Сохранить TWG</Button>
        {connection.configured && (
          <ConfirmDeleteButton kind="подключение TWG" name={connection.site ?? ""}
            pending={remove.isPending} onConfirm={() => remove.mutate(undefined, {
              onSuccess: () => toast.success("Подключение TWG удалено"),
              onError: toastError("Не удалось отключить TWG"),
            })} />
        )}
      </div>
    </form>
  );
}

export function TwgConnectionCard() {
  const query = useTwg();
  return (
    <Card>
      <CardTitle>Atlassian TWG</CardTitle>
      <QueryState isLoading={query.isLoading} isError={query.isError}
        errorLabel="Не удалось загрузить подключение TWG">
        {query.data && (query.data.enabled === false
          ? <p className="text-small text-text-2">TWG отключён администратором.</p>
          : <ConnectionForm key={`${query.data.configured}:${query.data.site}:${query.data.email}`}
            connection={query.data} />)}
      </QueryState>
    </Card>
  );
}
