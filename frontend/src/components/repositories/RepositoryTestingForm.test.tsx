import { screen } from "@testing-library/react";
import { expect } from "vitest";
import { RepositoryTestingForm } from "@/components/repositories/RepositoryTestingForm";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";
import type { Repository, TestProfile } from "@/lib/types";

const repository: Repository = {
  id: "r1", name: "shop", git_url: "https://example.com/shop.git",
  default_branch: "main", default_template_id: null, git_credential_id: null,
};
const profile: TestProfile = {
  compose_files: ["compose.yml"], service: "app", commands: { unit: "sh /app/scripts/unittests.sh" },
  environment: {}, timeout_seconds: 900, report_paths: [],
};

test("автозаполнение сохраняется только после нажатия «Сохранить»", async ({ api }) => {
  api.respond("POST /repositories/test-profile/detect", profile);
  const { user } = renderWithProviders(<RepositoryTestingForm repository={repository} />);
  await user.click(screen.getByRole("button", { name: "Заполнить из репозитория" }));
  await expect.poll(() => (screen.getByLabelText("Unit-тесты") as HTMLInputElement).value).toBe(profile.commands.unit);
  expect(api.mutations()).toHaveLength(1);
  await user.click(screen.getByRole("button", { name: "Сохранить" }));
  await expect.poll(() => api.mutations().length).toBe(2);
  expect(api.mutations()[1]).toMatchObject({
    method: "PATCH", path: "/repositories/r1", body: { test_profile: profile },
  });
});

test("некорректные переменные не отправляются на сервер", async ({ api, toasts }) => {
  const { user } = renderWithProviders(<RepositoryTestingForm repository={repository} />);
  await user.type(screen.getByLabelText("Переменные окружения"), "BROKEN");
  await user.click(screen.getByRole("button", { name: "Сохранить" }));
  expect(api.mutations()).toEqual([]);
  expect(toasts.error).toHaveBeenCalledWith("Переменные задаются в формате ИМЯ=значение");
});
