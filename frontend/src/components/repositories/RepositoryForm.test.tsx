import { screen } from "@testing-library/react";
import { expect, vi } from "vitest";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";
import { RepositoryForm } from "./RepositoryForm";

test("сохраняет выбранный доступ вместо приватного ключа", async ({ api }) => {
  api.respond("GET /git-credentials", [{ id: "cred1", name: "GitLab RioRise", host: "gitlab.example.com", kind: "https_token", username: "oauth2" }]);
  const saved = vi.fn();
  const { user } = renderWithProviders(<RepositoryForm onSaved={saved} onCancel={() => {}} />);
  await user.type(screen.getByLabelText("Название"), "repo");
  await user.type(screen.getByLabelText("Git URL"), "https://gitlab.example.com/repo.git");
  await user.click(screen.getByRole("combobox", { name: "Учётные данные Git" }));
  await user.click(await screen.findByRole("option", { name: "GitLab RioRise · gitlab.example.com" }));
  await user.click(screen.getByRole("button", { name: "Создать" }));
  expect(api.mutations()).toEqual([{ method: "POST", path: "/repositories", body: { name: "repo", git_url: "https://gitlab.example.com/repo.git", git_credential_id: "cred1", default_template_id: null } }]);
  expect(screen.queryByLabelText(/Deploy-ключ/)).not.toBeInTheDocument();
  await vi.waitFor(() => expect(saved).toHaveBeenCalled());
});
