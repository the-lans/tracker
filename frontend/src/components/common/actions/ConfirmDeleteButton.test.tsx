import { screen } from "@testing-library/react";
import { describe, expect, vi } from "vitest";
import { ConfirmDeleteButton } from "@/components/common/actions/ConfirmDeleteButton";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

function renderButton() {
  const onConfirm = vi.fn();
  const view = renderWithProviders(
    <ConfirmDeleteButton kind="пайплайн" name="Фича с ревью" onConfirm={onConfirm} />,
  );
  return { ...view, onConfirm };
}

describe("ConfirmDeleteButton", () => {
  test("удаляет только после подтверждения в диалоге", async () => {
    const { user, onConfirm } = renderButton();

    await user.click(screen.getByRole("button", { name: "Удалить Фича с ревью" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("«Фича с ревью»");
    expect(onConfirm).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Удалить" }));
    expect(onConfirm).toHaveBeenCalledOnce();
  });

  test("отмена закрывает диалог без удаления", async () => {
    const { user, onConfirm } = renderButton();

    await user.click(screen.getByRole("button", { name: "Удалить Фича с ревью" }));
    await user.click(screen.getByRole("button", { name: "Отмена" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(onConfirm).not.toHaveBeenCalled();
  });
});
