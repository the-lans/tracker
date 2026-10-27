import { screen } from "@testing-library/react";
import { describe, expect } from "vitest";
import { AllowedEmailsCard } from "@/components/admin/AllowedEmailsCard";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

describe("AllowedEmailsCard", () => {
  test("пока список грузится, пустое состояние не показывается", ({ api }) => {
    api.respond("GET /allowed-emails", []);
    renderWithProviders(<AllowedEmailsCard />);

    expect(screen.getByRole("status")).toHaveTextContent("Загрузка…");
    expect(screen.queryByText("Список допуска пуст")).not.toBeInTheDocument();
  });

  test.for([
    { emails: [], empty: true },
    { emails: [{ id: "e1", email: "admin@example.com" }], empty: false },
  ])("после загрузки пустое состояние: $empty", async ({ emails, empty }, { api }) => {
    api.respond("GET /allowed-emails", emails);
    renderWithProviders(<AllowedEmailsCard />);

    await screen.findByText(empty ? "Список допуска пуст" : "admin@example.com");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
