import { screen } from "@testing-library/react";
import { expect, vi } from "vitest";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";
import { GitCredentialsPanel } from "./GitCredentialsPanel";

test("пустой секрет при правке не заменяет сохранённый", async ({ api }) => {
  api.respond("GET /git-credentials", [{ id: "cred1", name: "GitLab", host: "gitlab.example.com", kind: "https_token", username: "oauth2" }]);
  const { user } = renderWithProviders(<GitCredentialsPanel />);
  await screen.findByText("GitLab");
  await user.click(screen.getByRole("button", { name: /Изменить GitLab/ }));
  await user.clear(screen.getByLabelText("Название"));
  await user.type(screen.getByLabelText("Название"), "GitLab RioRise");
  expect(screen.getByLabelText("Токен")).toHaveValue("");
  await user.click(screen.getByRole("button", { name: "Сохранить" }));
  await vi.waitFor(() => expect(api.mutations()).toEqual([{ method: "PUT", path: "/git-credentials/cred1", body: { name: "GitLab RioRise", host: "gitlab.example.com", kind: "https_token", username: "oauth2" } }]));
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
    },
  }]));
});
