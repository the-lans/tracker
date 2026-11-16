import { screen } from "@testing-library/react";
import { expect } from "vitest";
import { TwgConnectionCard } from "@/components/profile/TwgConnectionCard";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

test("подключение требует токен, отправляет и очищает секрет", async ({ api }) => {
  api.respond("GET /profile/twg", { enabled: true, configured: false, site: null, email: null });
  api.respond("PUT /profile/twg", {
    enabled: true, configured: true, site: "example.atlassian.net", email: "person@example.com",
  });
  const { user } = renderWithProviders(<TwgConnectionCard />);
  const token = await screen.findByLabelText("Токен Atlassian для TWG");
  await user.type(screen.getByLabelText("Сайт Atlassian"), "example.atlassian.net");
  await user.type(screen.getByLabelText("Email Atlassian"), "person@example.com");
  await user.click(screen.getByRole("button", { name: "Сохранить TWG" }));
  expect(api.mutations()).toEqual([]);
  await user.type(token, "personal-token");
  await user.click(screen.getByRole("button", { name: "Сохранить TWG" }));
  await expect.poll(() => api.mutations()).toEqual([{
    method: "PUT", path: "/profile/twg",
    body: { site: "example.atlassian.net", email: "person@example.com", token: "personal-token" },
  }]);
  expect(await screen.findByLabelText("Токен Atlassian для TWG")).toHaveValue("");
});

test("сохранённый токен не нужно вводить повторно", async ({ api }) => {
  const connection = {
    enabled: true, configured: true, site: "example.atlassian.net", email: "person@example.com",
  };
  api.respond("GET /profile/twg", connection);
  api.respond("PUT /profile/twg", connection);
  const { user } = renderWithProviders(<TwgConnectionCard />);
  expect(await screen.findByLabelText("Токен Atlassian для TWG")).toHaveValue("");
  await user.click(screen.getByRole("button", { name: "Сохранить TWG" }));
  await expect.poll(() => api.mutations()[0]?.body).toEqual({
    site: connection.site, email: connection.email, token: null,
  });
});

test("отключённый TWG не предлагает вводить секрет", async ({ api }) => {
  api.respond("GET /profile/twg", { enabled: false, configured: false });
  renderWithProviders(<TwgConnectionCard />);
  expect(await screen.findByText("TWG отключён администратором.")).toBeInTheDocument();
  expect(screen.queryByLabelText("Токен Atlassian для TWG")).not.toBeInTheDocument();
});

test("подключение удаляется после подтверждения, форма очищается", async ({ api }) => {
  api.respond("GET /profile/twg", {
    enabled: true, configured: true, site: "example.atlassian.net", email: "person@example.com",
  });
  api.respond("DELETE /profile/twg", {
    enabled: true, configured: false, site: null, email: null,
  });
  const { user } = renderWithProviders(<TwgConnectionCard />);
  await user.click(await screen.findByRole("button", { name: "Удалить example.atlassian.net" }));
  expect(api.mutations()).toEqual([]);
  await user.click(screen.getByRole("button", { name: /^Удалить$/ }));
  await expect.poll(() => api.mutations()).toEqual([
    { method: "DELETE", path: "/profile/twg", body: undefined },
  ]);
  await expect.poll(() => screen.getByLabelText("Сайт Atlassian")).toHaveValue("");
});
