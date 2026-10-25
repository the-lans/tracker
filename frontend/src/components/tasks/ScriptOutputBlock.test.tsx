import { screen } from "@testing-library/react";
import { describe, expect } from "vitest";
import { ScriptOutputBlock } from "@/components/tasks/ScriptOutputBlock";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

describe("ScriptOutputBlock", () => {
  test.for([
    { exitCode: 0, label: "exit 0", tone: "text-term-success" },
    { exitCode: 1, label: "exit 1", tone: "text-term-error" },
    { exitCode: 137, label: "exit 137", tone: "text-term-error" },
    { exitCode: null, label: "выполняется…", tone: "text-term-muted" },
  ])("код выхода $exitCode → «$label»", ({ exitCode, label, tone }) => {
    renderWithProviders(<ScriptOutputBlock stdout="ok" exitCode={exitCode} />);

    expect(screen.getByText(label)).toHaveClass(tone);
  });

  test("пустой вывод подписан", () => {
    renderWithProviders(<ScriptOutputBlock stdout={null} exitCode={0} />);

    expect(screen.getByText("(пусто)")).toBeInTheDocument();
  });

  test("вывод, пришедший после «(пусто)», свёрнут", () => {
    const { rerender } = renderWithProviders(<ScriptOutputBlock stdout={null} exitCode={null} />);

    rerender(<ScriptOutputBlock stdout={`${"line\n".repeat(100)}ИТОГ`} exitCode={1} />);

    expect(screen.getByRole("button", { name: "Показать полностью →" })).toBeInTheDocument();
    expect(screen.queryByText(/ИТОГ/)).not.toBeInTheDocument();
  });
});
