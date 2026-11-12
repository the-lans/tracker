import { screen, within } from "@testing-library/react";
import { describe, expect } from "vitest";
import { LibraryPage } from "@/pages/LibraryPage";
import { makeNode } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const prompt = makeNode({ id: "l1", pipeline_id: null, is_library_item: true, name: "Ревью" });

describe("LibraryPage", () => {
  test.for([
    {
      response: { error: { status: 409, message: "Промт выполняют ноды пайплайнов — вместо удаления доступна архивация" } },
      shown: "Промт выполняют ноды пайплайнов — вместо удаления доступна архивация",
    },
    { response: { error: { status: 500, message: "Сбой сервера" } }, shown: "Сбой сервера" },
  ])("отказ в удалении → «$shown»", async ({ response, shown }, { api, toasts }) => {
    api.respond("GET /nodes", [prompt]);
    api.respond("DELETE /nodes/l1", response);
    const { user } = renderWithProviders(<LibraryPage />);

    await user.click(await screen.findByRole("button", { name: "Удалить Ревью" }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Удалить" }));

    await expect.poll(() => toasts.error.mock.calls).toEqual([[shown]]);
  });
});
