import { screen } from "@testing-library/react";
import { describe, expect } from "vitest";
import { TaskCodeLink } from "@/components/tasks/TaskCodeLink";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const TASK_ID = "0a1b2c3d-0000-4000-8000-000000000001";

describe("TaskCodeLink", () => {
  test.for([
    { code: "RR-7", label: "RR-7" },
    { code: null, label: "0a1b2c3d" },
  ])("код $code → ссылка «$label» на задачу", ({ code, label }) => {
    renderWithProviders(<TaskCodeLink taskId={TASK_ID} code={code} />);

    expect(screen.getByRole("link", { name: label })).toHaveAttribute("href", `/tasks/${TASK_ID}`);
  });

  test("без задачи — код текстом, без ссылки", () => {
    renderWithProviders(<TaskCodeLink taskId={null} code="RR-7" />);

    expect(screen.getByText("RR-7")).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
  });

  test("ни задачи, ни кода — ничего", () => {
    const { container } = renderWithProviders(<TaskCodeLink taskId={null} />);

    expect(container).toBeEmptyDOMElement();
  });
});
