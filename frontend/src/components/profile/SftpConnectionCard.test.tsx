import { screen } from "@testing-library/react";
import { describe, expect } from "vitest";
import { SftpConnectionCard } from "@/components/profile/SftpConnectionCard";
import type { SftpConnection } from "@/lib/types";
import type { MockedApi } from "@/test/apiMock";
import { makeUser } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const COMMAND = "sshfs -p 2222 anna@tracker.example.com:/ ~/tracker -o reconnect";

function renderCard(api: MockedApi, overrides: Partial<SftpConnection> = {}) {
  api.respond("GET /profile/sftp", {
    host: "tracker.example.com",
    port: 2222,
    username: "anna",
    host_key_fingerprint: "SHA256:Hk12Hk34",
    ...overrides,
  });
  api.respond("GET /profile", makeUser());
  return renderWithProviders(<SftpConnectionCard />);
}

describe("SftpConnectionCard", () => {
  test("без логина — подсказка, к кому обратиться", async ({ api }) => {
    renderCard(api, { username: null });

    expect(await screen.findByText("Логин не назначен")).toBeInTheDocument();
    expect(screen.queryByText(/sshfs/)).not.toBeInTheDocument();
  });

  test("команда подключения собирается из сервера, порта и логина", async ({ api }) => {
    renderCard(api);

    expect(await screen.findByText(COMMAND)).toBeInTheDocument();
    expect(screen.getByText("SHA256:Hk12Hk34")).toBeInTheDocument();
  });

  test("копирование кладёт в буфер ту же команду", async ({ api, toasts }) => {
    const { user } = renderCard(api);

    await user.click(await screen.findByRole("button", { name: "Копировать команду подключения" }));

    await expect.poll(() => navigator.clipboard.readText()).toBe(COMMAND);
    await expect.poll(() => toasts.success.mock.calls).toEqual([["Скопировано"]]);
  });

  test("шлюз ещё не запускался — отпечатка пока нет", async ({ api }) => {
    renderCard(api, { host_key_fingerprint: null });

    expect(await screen.findByText("появится после первого запуска шлюза")).toBeInTheDocument();
  });
});
