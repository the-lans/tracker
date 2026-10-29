import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";
import { type MobileTaskTab, TaskMobileTabs } from "@/components/tasks/TaskMobileTabs";

describe("TaskMobileTabs", () => {
  test.for<{ value: MobileTaskTab; label: string }>([
    { value: "overview", label: "Обзор" },
    { value: "dialogue", label: "Диалог" },
    { value: "logs", label: "Логи" },
  ])("выбрана «$label» — отмечена только она", ({ value, label }) => {
    render(<TaskMobileTabs value={value} onChange={() => undefined} />);

    expect(screen.getByRole("tab", { selected: true })).toHaveTextContent(label);
    expect(screen.getAllByRole("tab", { selected: false })).toHaveLength(2);
  });

  test("нажатие переключает вкладку", async () => {
    const onChange = vi.fn();
    render(<TaskMobileTabs value="dialogue" onChange={onChange} />);

    await userEvent.click(screen.getByRole("tab", { name: "Логи" }));

    expect(onChange).toHaveBeenCalledWith("logs");
  });
});
