import { screen } from "@testing-library/react";
import { useLocation } from "react-router-dom";
import { expect } from "vitest";
import { ProfilePage } from "@/pages/ProfilePage";
import { makeUser } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

function LocationProbe() {
  return <div data-testid="location">{useLocation().search}</div>;
}

test("по умолчанию показан аккаунт, остальные настройки скрыты", () => {
  renderWithProviders(<ProfilePage />);
  expect(screen.getByRole("tab", { name: "Аккаунт и безопасность" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByRole("button", { name: "Выйти" })).toBeVisible();
  expect(screen.queryByText("SSH-ключ для SFTP")).not.toBeInTheDocument();
});

test("раздел файлов открывается по прямой ссылке", ({ api }) => {
  api.respond("GET /profile", makeUser());
  renderWithProviders(<ProfilePage />, { path: "/profile?tab=files" });
  expect(screen.getByRole("tab", { name: "Доступ к файлам" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByText("SSH-ключ для SFTP")).toBeVisible();
  expect(screen.getByText("Доступ к файлам задач (SFTP)")).toBeVisible();
  expect(screen.queryByRole("button", { name: "Выйти" })).not.toBeInTheDocument();
});

test("переключение раздела меняет URL и показывает только его настройки", async ({ api }) => {
  api.respond("GET /profile", makeUser());
  api.respond("GET /jira/server", { jira_url: null });
  api.respond("GET /profile/google-calendar", null);
  const { user } = renderWithProviders(<><ProfilePage /><LocationProbe /></>);
  await user.click(screen.getByRole("tab", { name: "Подключения" }));
  expect(screen.getByTestId("location")).toHaveTextContent("?tab=connections");
  expect(screen.getByText("Google Calendar", { exact: true })).toBeVisible();
  expect(screen.queryByRole("button", { name: "Выйти" })).not.toBeInTheDocument();
});

test("возврат из Google открывает подключения и показывает результат", async ({ api, toasts }) => {
  api.respond("GET /profile", makeUser());
  api.respond("GET /jira/server", { jira_url: null });
  api.respond("GET /profile/google-calendar", null);
  renderWithProviders(<ProfilePage />, { path: "/profile?tab=connections&calendar=connected" });
  expect(screen.getByRole("tab", { name: "Подключения" })).toHaveAttribute("aria-selected", "true");
  await expect.poll(() => toasts.success.mock.calls).toContainEqual(["Google Calendar подключён"]);
});
