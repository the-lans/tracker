import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useUpdateRepository } from "@/hooks/useRepositories";
import { api } from "@/lib/apiClient";
import { toastError } from "@/lib/errors";
import type { Repository, TestProfile } from "@/lib/types";

const DEFAULT_PROFILE: TestProfile = {
  compose_files: ["compose.yml"], service: "app", commands: {},
  environment: {}, timeout_seconds: 900, report_paths: [],
};
const CHECKS = [{ key: "lint", label: "Линтеры" }, { key: "unit", label: "Unit-тесты" },
  { key: "integration", label: "Интеграционные тесты" }];

export function RepositoryTestingForm({ repository }: { repository: Repository }) {
  const [profile, setProfile] = useState(repository.test_profile ?? DEFAULT_PROFILE);
  const [files, setFiles] = useState(profile.compose_files.join("\n"));
  const [reports, setReports] = useState(profile.report_paths.join("\n"));
  const [environment, setEnvironment] = useState(Object.entries(profile.environment).map(([k, v]) => `${k}=${v}`).join("\n"));
  const save = useUpdateRepository(repository.id);
  const detect = useMutation({
    mutationFn: () => api.post<TestProfile>("/repositories/test-profile/detect", {
      git_url: repository.git_url, git_credential_id: repository.git_credential_id,
      branch: repository.default_branch,
    }),
    onSuccess: (value) => {
      setProfile(value);
      setFiles(value.compose_files.join("\n"));
      setReports(value.report_paths.join("\n"));
      setEnvironment(Object.entries(value.environment).map(([k, v]) => `${k}=${v}`).join("\n"));
      toast.success("Поля заполнены. Проверьте настройки и сохраните профиль");
    },
    onError: toastError("Не удалось заполнить профиль"),
  });
  function handleSave() {
    const variables: Record<string, string> = {};
    for (const line of environment.split("\n").filter((value) => value.trim())) {
      const separator = line.indexOf("=");
      if (separator < 1) { toast.error("Переменные задаются в формате ИМЯ=значение"); return; }
      variables[line.slice(0, separator).trim()] = line.slice(separator + 1);
    }
    save.mutate({ test_profile: {
      ...profile, environment: variables,
      commands: Object.fromEntries(Object.entries(profile.commands).filter(([, value]) => value.trim())),
      compose_files: files.split("\n").map((value) => value.trim()).filter(Boolean),
      report_paths: reports.split("\n").map((value) => value.trim()).filter(Boolean),
    } }, { onSuccess: () => toast.success("Профиль тестирования сохранён"),
      onError: toastError("Не удалось сохранить профиль") });
  }
  return <div className="flex flex-col gap-3">
    <div><Label htmlFor="check-files">Compose-файлы</Label>
      <Textarea id="check-files" value={files} onChange={(e) => setFiles(e.target.value)} />
      <p className="text-small text-text-3">Относительные пути, каждый с новой строки. Порядок учитывается.</p></div>
    <div><Label htmlFor="check-service">Сервис выполнения</Label>
      <Input id="check-service" value={profile.service} onChange={(e) => setProfile({ ...profile, service: e.target.value })} /></div>
    <div><Label htmlFor="check-workdir">Рабочая директория в контейнере</Label>
      <Input id="check-workdir" placeholder="Из настроек сервиса или образа"
        value={profile.working_directory ?? ""}
        onChange={(e) => setProfile({ ...profile, working_directory: e.target.value || null })} /></div>
    {CHECKS.map(({ key, label }) => <div key={key}><Label htmlFor={`check-${key}`}>{label}</Label>
      <Input id={`check-${key}`} placeholder={`sh /app/scripts/${key}.sh`} value={profile.commands[key] ?? ""}
        onChange={(e) => setProfile({ ...profile, commands: { ...profile.commands, [key]: e.target.value } })} /></div>)}
    <div><Label htmlFor="check-environment">Переменные окружения</Label>
      <Textarea id="check-environment" value={environment} placeholder="POSTGRES_HOST=db"
        onChange={(e) => setEnvironment(e.target.value)} /></div>
    <div><Label htmlFor="check-timeout">Таймаут, секунды</Label>
      <Input id="check-timeout" type="number" min={10} max={7200} value={profile.timeout_seconds}
        onChange={(e) => setProfile({ ...profile, timeout_seconds: Number(e.target.value) })} /></div>
    <div><Label htmlFor="check-reports">Пути к отчётам</Label>
      <Textarea id="check-reports" value={reports} onChange={(e) => setReports(e.target.value)} />
      <p className="text-small text-text-3">Пути внутри репозитория. Отчёты сохранятся в файлах задачи.</p></div>
    <div className="flex justify-between gap-2">
      <Button variant="secondary" disabled={detect.isPending || save.isPending} onClick={() => detect.mutate()}>
        {detect.isPending ? "Чтение репозитория…" : "Заполнить из репозитория"}
      </Button>
      <Button disabled={save.isPending || detect.isPending || !profile.service || !files.trim()} onClick={handleSave}>Сохранить</Button>
    </div>
  </div>;
}
