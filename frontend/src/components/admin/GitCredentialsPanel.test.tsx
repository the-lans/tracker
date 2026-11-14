import { screen } from "@testing-library/react";
import { expect, vi } from "vitest";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";
import type { GitCredential } from "./gitCredentials.types";
import { GitCredentialsPanel } from "./GitCredentialsPanel";

const HTTPS: GitCredential = {
  id: "cred1",
  name: "GitLab",
  host: "gitlab.example.com",
  kind: "https_token",
  username: "oauth2",
  gitlab_api_enabled: false,
  gitlab_api_url: null,
  gitlab_api_token_set: false,
  ssh_host_key_fingerprints: [],
};
const SAVED = { name: "GitLab", host: "gitlab.example.com", kind: "https_token", username: "oauth2" };

test("пустой секрет при правке не заменяет сохранённый", async ({ api }) => {
  api.respond("GET /git-credentials", [HTTPS]);
  const { user } = renderWithProviders(<GitCredentialsPanel />);
  await screen.findByText("GitLab");
  await user.click(screen.getByRole("button", { name: /Изменить GitLab/ }));
  await user.clear(screen.getByLabelText("Название"));
  await user.type(screen.getByLabelText("Название"), "GitLab Example");
  expect(screen.getByLabelText("Токен")).toHaveValue("");
  await user.click(screen.getByRole("button", { name: "Сохранить" }));
  await vi.waitFor(() => expect(api.mutations()).toEqual([{
    method: "PUT", path: "/git-credentials/cred1", body: {
      ...SAVED, name: "GitLab Example", gitlab_api_enabled: false, gitlab_api_url: null,
    },
  }]));
});

test("SSH-ключ скрыт при вставке и сохраняется со всеми переводами строк", async ({ api }) => {
  api.respond("GET /git-credentials", []);
  const { user } = renderWithProviders(<GitCredentialsPanel />);
  await user.click(screen.getByRole("button", { name: "Добавить" }));
  await user.type(screen.getByLabelText("Название"), "SSH");
  await user.type(screen.getByLabelText("Git-хост"), "git.example.com");
  await user.click(screen.getByRole("combobox", { name: "Тип доступа" }));
  await user.click(screen.getByRole("option", { name: "SSH-ключ" }));
  const input = screen.getByLabelText("Приватный SSH-ключ без пароля");
  expect(input).toHaveAttribute("type", "password");
  const key = "-----BEGIN OPENSSH PRIVATE KEY-----\nkey-data\n-----END OPENSSH PRIVATE KEY-----\n";
  await user.click(input);
  await user.paste(key);
  await user.click(screen.getByRole("button", { name: "Показать секрет" }));
  expect(screen.getByLabelText("Приватный SSH-ключ без пароля")).toHaveValue(key);
  await user.click(screen.getByRole("button", { name: "Скрыть секрет" }));
  expect(screen.getByLabelText("Приватный SSH-ключ без пароля")).toHaveAttribute("type", "password");
  await user.click(screen.getByRole("button", { name: "Сохранить" }));
  await vi.waitFor(() => expect(api.mutations()).toEqual([{
    method: "POST", path: "/git-credentials", body: {
      name: "SSH", host: "git.example.com", kind: "ssh_key", username: "oauth2", secret: key,
      gitlab_api_enabled: false, gitlab_api_url: null,
    },
  }]));
});

test.for([
  {
    title: "HTTPS: тот же токен — без токена API",
    saved: HTTPS, ownToken: false, token: "", url: "",
    api: { gitlab_api_enabled: true, gitlab_api_url: null },
  },
  {
    title: "HTTPS: возврат к тому же токену удаляет свой",
    saved: { ...HTTPS, gitlab_api_enabled: true, gitlab_api_token_set: true },
    ownToken: true, token: "", url: "", toggleBack: true,
    api: { gitlab_api_enabled: true, gitlab_api_url: null, gitlab_api_token: "" },
  },
  {
    title: "HTTPS: свой токен и адрес",
    saved: HTTPS, ownToken: true, token: "glpat-api", url: " https://gitlab.example.com:8443 ",
    api: {
      gitlab_api_enabled: true, gitlab_api_url: "https://gitlab.example.com:8443",
      gitlab_api_token: "glpat-api",
    },
  },
])("$title", async ({ saved, ownToken, token, url, toggleBack, api: apiBody }, { api }) => {
  api.respond("GET /git-credentials", [saved]);
  const { user } = renderWithProviders(<GitCredentialsPanel />);
  await user.click(await screen.findByRole("button", { name: /Изменить GitLab/ }));
  if (!saved.gitlab_api_enabled) {
    await user.click(screen.getByRole("checkbox", { name: "Статус MR через GitLab API" }));
  }
  const same = screen.getByRole("checkbox", { name: "Тот же токен, что для Git" });
  if (ownToken === (same.getAttribute("data-state") === "checked")) await user.click(same);
  if (toggleBack) await user.click(same);
  if (token) await user.type(screen.getByLabelText("Токен GitLab API"), token);
  if (url) await user.type(screen.getByLabelText("Адрес GitLab"), url);
  await user.click(screen.getByRole("button", { name: "Сохранить" }));
  await vi.waitFor(() => expect(api.mutations()).toEqual([{
    method: "PUT", path: "/git-credentials/cred1", body: { ...SAVED, ...apiBody },
  }]));
});

test.for([
  { kind: "ssh_key" as const, tokenSet: false, blocked: true },
  { kind: "ssh_key" as const, tokenSet: true, blocked: false },
])("SSH с API: токен сохранён — $tokenSet → «Сохранить» недоступна — $blocked", async (
  { kind, tokenSet, blocked },
  { api },
) => {
  api.respond("GET /git-credentials", [{
    ...HTTPS, kind, username: "git", gitlab_api_enabled: true, gitlab_api_token_set: tokenSet,
  }]);
  const { user } = renderWithProviders(<GitCredentialsPanel />);
  expect(await screen.findByText(/SSH · gitlab\.example\.com · статус MR/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /Изменить GitLab/ }));
  expect(screen.queryByRole("checkbox", { name: "Тот же токен, что для Git" })).not.toBeInTheDocument();
  const button = screen.getByRole("button", { name: "Сохранить" });
  if (blocked) expect(button).toBeDisabled();
  else expect(button).toBeEnabled();
  if (blocked) {
    await user.type(screen.getByLabelText("Токен GitLab API"), "glpat-api");
    expect(button).toBeEnabled();
  }
});

test.for([
  { gitlab_api: "disabled", kind: "success", text: "Чтение доступно. Право записи этой проверкой не проверяется." },
  { gitlab_api: "ok", kind: "success", text: "не проверяется. GitLab API доступен." },
  { gitlab_api: "GitLab отклонил токен API (401)", kind: "error", text: "GitLab API: GitLab отклонил токен API (401)" },
  { gitlab_api: "disabled", kind: "success", text: "Сверьте ключ хоста SHA256:abc с Git-сервером.", fingerprints: ["SHA256:abc"] },
] as const)("проверка доступа: API $gitlab_api", async ({ gitlab_api, kind, text, ...rest }, { api, toasts }) => {
  const fingerprints = "fingerprints" in rest ? [...(rest.fingerprints ?? [])] : [];
  api.respond("GET /git-credentials", [HTTPS]);
  api.respond("POST /git-credentials/cred1/check", {
    read_access: true, gitlab_api, ssh_host_key_fingerprints: fingerprints,
  });
  const { user } = renderWithProviders(<GitCredentialsPanel />);
  await user.click(await screen.findByRole("button", { name: /Изменить GitLab/ }));
  await user.type(screen.getByLabelText("URL для проверки чтения"), "https://gitlab.example.com/g/p.git");
  await user.click(screen.getByRole("button", { name: "Проверить сохранённый доступ" }));
  await vi.waitFor(() => expect(toasts[kind]).toHaveBeenCalledTimes(1));
  expect(String(toasts[kind].mock.calls[0][0])).toContain(text);
  expect(toasts[kind === "error" ? "success" : "error"]).not.toHaveBeenCalled();
});

test.for([
  { tokenSet: false, same: true },
  { tokenSet: true, same: false },
])("HTTPS: сохранён свой токен — $tokenSet → «тот же токен» — $same", async ({ tokenSet, same }, { api }) => {
  api.respond("GET /git-credentials", [{ ...HTTPS, gitlab_api_enabled: true, gitlab_api_token_set: tokenSet }]);
  const { user } = renderWithProviders(<GitCredentialsPanel />);
  await user.click(await screen.findByRole("button", { name: /Изменить GitLab/ }));
  const checkbox = screen.getByRole("checkbox", { name: "Тот же токен, что для Git" });
  if (same) expect(checkbox).toBeChecked();
  else expect(checkbox).not.toBeChecked();
  expect(screen.queryByLabelText("Токен GitLab API") !== null).toBe(!same);
});

test("новый доступ: смена HTTPS на SSH требует токен API", async ({ api }) => {
  api.respond("GET /git-credentials", []);
  const { user } = renderWithProviders(<GitCredentialsPanel />);
  await user.click(screen.getByRole("button", { name: "Добавить" }));
  await user.type(screen.getByLabelText("Название"), "SSH");
  await user.type(screen.getByLabelText("Git-хост"), "git.example.com");
  await user.click(screen.getByRole("checkbox", { name: "Статус MR через GitLab API" }));
  await user.click(screen.getByRole("combobox", { name: "Тип доступа" }));
  await user.click(screen.getByRole("option", { name: "SSH-ключ" }));
  await user.click(screen.getByLabelText("Приватный SSH-ключ без пароля"));
  await user.paste("key");
  expect(screen.getByRole("button", { name: "Сохранить" })).toBeDisabled();
  expect(screen.getByLabelText("Токен GitLab API")).toBeInTheDocument();
});

const SSH: GitCredential = { ...HTTPS, id: "ssh1", name: "SSH", kind: "ssh_key", host: "git.example.com" };
const SSH_SAVED = { name: "SSH", host: "git.example.com", kind: "ssh_key", username: "oauth2" };
const FINGERPRINT = "SHA256:abc";

test.for([
  { fingerprints: [FINGERPRINT], summary: `ключ хоста ${FINGERPRINT}` },
  { fingerprints: [], summary: "ключ хоста ещё не получен" },
])("строка SSH-доступа: $summary", async ({ fingerprints, summary }, { api }) => {
  api.respond("GET /git-credentials", [{ ...SSH, ssh_host_key_fingerprints: fingerprints }]);
  renderWithProviders(<GitCredentialsPanel />);

  expect(await screen.findByText(new RegExp(summary))).toBeInTheDocument();
});

test.for([
  { action: "без правок ключ не передаётся", known_hosts: undefined, reset: false },
  { action: "вставленные строки заменяют ключ", known_hosts: "git.example.com ssh-ed25519 AAAA", reset: false },
  { action: "сброс отправляет пустую строку", known_hosts: "", reset: true },
])("ключ хоста: $action", async ({ known_hosts, reset }, { api }) => {
  api.respond("GET /git-credentials", [{ ...SSH, ssh_host_key_fingerprints: [FINGERPRINT] }]);
  const { user } = renderWithProviders(<GitCredentialsPanel />);
  await user.click(await screen.findByRole("button", { name: /Изменить SSH/ }));

  if (known_hosts) await user.type(screen.getByLabelText("Ключ хоста (known_hosts)"), known_hosts);
  if (reset) await user.click(screen.getByRole("button", { name: "Сбросить ключ хоста" }));
  await user.click(screen.getByRole("button", { name: "Сохранить" }));

  await vi.waitFor(() => expect(api.mutations()).toEqual([{
    method: "PUT", path: "/git-credentials/ssh1", body: {
      ...SSH_SAVED, gitlab_api_enabled: false, gitlab_api_url: null,
      ...(known_hosts === undefined ? {} : { ssh_known_hosts: known_hosts }),
    },
  }]));
});

test("проверка запоминает ключ хоста: отпечаток в форме, список перечитывается", async ({ api, toasts }) => {
  api.respond("GET /git-credentials", [SSH]);
  api.respond("POST /git-credentials/ssh1/check", {
    read_access: true, gitlab_api: "disabled", ssh_host_key_fingerprints: [FINGERPRINT],
  });
  const { user } = renderWithProviders(<GitCredentialsPanel />);
  await user.click(await screen.findByRole("button", { name: /Изменить SSH/ }));
  expect(screen.queryByRole("button", { name: "Сбросить ключ хоста" })).not.toBeInTheDocument();

  await user.type(screen.getByLabelText("URL для проверки чтения"), "ssh://git@git.example.com/g/p.git");
  await user.click(screen.getByRole("button", { name: "Проверить сохранённый доступ" }));

  await vi.waitFor(() => expect(toasts.success).toHaveBeenCalledTimes(1));
  expect(screen.getByText(new RegExp(`Сохранён: ${FINGERPRINT}`))).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Сбросить ключ хоста" })).toBeInTheDocument();
  await vi.waitFor(() => expect(
    api.requests.filter((request) => request.method === "GET" && request.path === "/git-credentials"),
  ).toHaveLength(2));
});
