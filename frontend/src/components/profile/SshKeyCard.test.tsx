import { screen, within } from "@testing-library/react";
import { describe, expect } from "vitest";
import { SshKeyCard } from "@/components/profile/SshKeyCard";
import type { User } from "@/lib/types";
import type { MockedApi } from "@/test/apiMock";
import { makeUser } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const PUBLIC_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKey anna@example.com";
const FINGERPRINT = "SHA256:Ab12Cd34Ef56Gh78";

const withKey = makeUser({ ssh_public_key: PUBLIC_KEY, ssh_key_fingerprint: FINGERPRINT });

function renderCard(api: MockedApi, profile: User = makeUser()) {
  api.respond("GET /profile", profile);
  api.respond("PUT /profile/ssh-key", withKey);
  api.respond("DELETE /profile/ssh-key", makeUser());
  return renderWithProviders(<SshKeyCard />);
}

describe("SshKeyCard", () => {
  describe("ключа нет", () => {
    test("пустой ключ сохранить нельзя", async ({ api }) => {
      const { user } = renderCard(api);

      await user.type(await screen.findByLabelText("Публичный ключ"), "   ");

      expect(screen.getByText("Ключ не добавлен")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Сохранить ключ" })).toBeDisabled();
    });

    test("сохранённый ключ сразу виден с отпечатком", async ({ api, toasts }) => {
      const { user } = renderCard(api);

      await user.type(await screen.findByLabelText("Публичный ключ"), PUBLIC_KEY);
      await user.click(screen.getByRole("button", { name: "Сохранить ключ" }));

      expect(api.mutations()).toEqual([
        { method: "PUT", path: "/profile/ssh-key", body: { public_key: PUBLIC_KEY } },
      ]);
      expect(await screen.findByText("ssh-ed25519 · anna@example.com")).toBeInTheDocument();
      expect(screen.getByText(FINGERPRINT)).toBeInTheDocument();
      expect(toasts.success).toHaveBeenCalledWith("Ключ сохранён — доступ по SFTP открыт");
    });

    test("неверный ключ — сообщение сервера, форма остаётся", async ({ api, toasts }) => {
      const { user } = renderCard(api);
      api.respond("PUT /profile/ssh-key", { error: { status: 422, message: "Это не публичный SSH-ключ" } });

      await user.type(await screen.findByLabelText("Публичный ключ"), "-----BEGIN OPENSSH PRIVATE KEY-----");
      await user.click(screen.getByRole("button", { name: "Сохранить ключ" }));

      await expect.poll(() => toasts.error.mock.calls).toEqual([["Это не публичный SSH-ключ"]]);
      expect(screen.getByLabelText("Публичный ключ")).toBeInTheDocument();
    });
  });

  describe("ключ есть", () => {
    test.for([
      { key: PUBLIC_KEY, title: "ssh-ed25519 · anna@example.com" },
      { key: "ssh-rsa AAAAB3NzaC1yc2E", title: "ssh-rsa" },
    ])("заголовок ключа: $title", async ({ key, title }, { api }) => {
      renderCard(api, makeUser({ ssh_public_key: key, ssh_key_fingerprint: FINGERPRINT }));

      expect(await screen.findByText(title)).toBeInTheDocument();
      expect(screen.queryByLabelText("Публичный ключ")).not.toBeInTheDocument();
    });

    test("отмена замены возвращает текущий ключ без запроса", async ({ api }) => {
      const { user } = renderCard(api, withKey);

      await user.click(await screen.findByRole("button", { name: "Заменить" }));
      await user.click(screen.getByRole("button", { name: "Отмена" }));

      expect(screen.getByText(FINGERPRINT)).toBeInTheDocument();
      expect(api.mutations()).toEqual([]);
    });

    test("удаление после подтверждения возвращает форму", async ({ api }) => {
      const { user } = renderCard(api, withKey);

      await user.click(await screen.findByRole("button", { name: "Удалить ssh-ed25519 · anna@example.com" }));
      await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Удалить" }));

      expect(api.mutations()).toEqual([{ method: "DELETE", path: "/profile/ssh-key", body: undefined }]);
      expect(await screen.findByText("Ключ не добавлен")).toBeInTheDocument();
    });
  });
});
