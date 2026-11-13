import { screen } from "@testing-library/react";
import { describe, expect, vi } from "vitest";
import { Pagination } from "@/components/common/navigation/Pagination";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

function renderPagination(page: number, total: number) {
  const onPageChange = vi.fn();
  const result = renderWithProviders(
    <Pagination page={page} pageSize={20} total={total} onPageChange={onPageChange} />,
  );
  return { ...result, onPageChange };
}

describe("Pagination", () => {
  test.for([0, 1, 20])("%i записей — одна страница, навигации нет", (total) => {
    renderPagination(1, total);

    expect(screen.queryByRole("navigation", { name: "Страницы" })).not.toBeInTheDocument();
  });

  test.for([
    { page: 1, total: 21, label: "Страница 1 из 2", back: false, forward: true },
    { page: 2, total: 41, label: "Страница 2 из 3", back: true, forward: true },
    { page: 3, total: 41, label: "Страница 3 из 3", back: true, forward: false },
  ])("$label: назад — $back, вперёд — $forward", ({ page, total, label, back, forward }) => {
    renderPagination(page, total);

    expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Предыдущая страница" }).hasAttribute("disabled")).toBe(!back);
    expect(screen.getByRole("button", { name: "Следующая страница" }).hasAttribute("disabled")).toBe(!forward);
  });

  test.for([
    { button: "Предыдущая страница", next: 1 },
    { button: "Следующая страница", next: 3 },
  ])("«$button» → страница $next", async ({ button, next }) => {
    const { user, onPageChange } = renderPagination(2, 60);

    await user.click(screen.getByRole("button", { name: button }));

    expect(onPageChange).toHaveBeenCalledWith(next);
  });
});
