import { screen } from "@testing-library/react";
import { describe, expect } from "vitest";
import { TaskRepositoriesCard } from "@/components/tasks/TaskRepositoriesCard";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const EMPTY_TITLE = "Репозитории не привязаны";

describe("TaskRepositoriesCard", () => {
  test.for([
    { state: "загрузка", response: () => new Promise(() => {}), loading: true },
    { state: "пустой список", response: [], loading: false },
  ])("$state", async (
    { response, loading },
    { api },
  ) => {
    api.respond("GET /tasks/t1/repositories", response);
    renderWithProviders(<TaskRepositoriesCard taskId="t1" />);

    if (loading) {
      expect(await screen.findByRole("status")).toHaveTextContent("Загрузка…");
      expect(screen.queryByText(EMPTY_TITLE)).not.toBeInTheDocument();
    } else {
      expect(await screen.findByText(EMPTY_TITLE)).toBeInTheDocument();
      expect(screen.queryByRole("status")).not.toBeInTheDocument();
    }
  });
});
