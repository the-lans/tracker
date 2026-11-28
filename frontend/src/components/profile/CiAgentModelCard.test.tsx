import { screen, waitFor } from "@testing-library/react";
import { describe, expect } from "vitest";
import { CiAgentModelCard } from "@/components/profile/CiAgentModelCard";
import { makeUser } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

describe("CiAgentModelCard", () => {
  test("сохраняет выбранную модель CI-агентов", async ({ api }) => {
    api.respond("GET /profile", makeUser());
    api.respond("PUT /profile/ci-agent-model", makeUser({ ci_agent_model: "another-model" }));
    const { user } = renderWithProviders(<CiAgentModelCard />);
    const input = await screen.findByLabelText("Модель для CI-агентов");
    expect(input).toHaveValue("gpt-6-luna");
    expect(screen.getByRole("button", { name: "Сохранить" })).toBeDisabled();
    await user.clear(input);
    await user.type(input, "another-model");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => expect(api.mutations()).toEqual([
      { method: "PUT", path: "/profile/ci-agent-model", body: { model: "another-model" } },
    ]));
    await waitFor(() => expect(screen.getByRole("button", { name: "Сохранить" })).toBeDisabled());
  });
});
