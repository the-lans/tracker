import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { DateSeparator } from "@/components/tasks/DateSeparator";

describe("DateSeparator", () => {
  test("показывает дату и не мешает счёту событий сессии", () => {
    const at = new Date(2026, 10, 19, 9, 0).getTime();
    const year = new Date().getFullYear();
    render(<DateSeparator at={at} />);

    expect(screen.getByRole("separator")).toHaveTextContent(
      year === 2026 ? "19 ноября" : /19 ноября 2026/,
    );
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });
});
