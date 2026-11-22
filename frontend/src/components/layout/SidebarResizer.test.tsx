import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SidebarResizer } from "@/components/layout/SidebarResizer";

function setup(width = 248) {
  const onChange = vi.fn();
  const onReset = vi.fn();
  render(<SidebarResizer width={width} onChange={onChange} onReset={onReset} />);
  return { handle: screen.getByRole("separator", { name: "Ширина меню" }), onChange, onReset };
}

describe("SidebarResizer", () => {
  it("описывает текущую ширину", () => {
    const { handle } = setup(300);
    expect(handle).toHaveAttribute("aria-valuenow", "300");
  });

  it("перетаскивание меняет ширину на смещение курсора и заканчивается по отпусканию", () => {
    const { handle, onChange } = setup(248);

    fireEvent.pointerDown(handle, { clientX: 248, pointerId: 1 });
    fireEvent.pointerMove(handle, { clientX: 300, pointerId: 1 });
    expect(onChange).toHaveBeenLastCalledWith(300);

    fireEvent.pointerUp(handle, { pointerId: 1 });
    onChange.mockClear();
    fireEvent.pointerMove(handle, { clientX: 400, pointerId: 1 });
    expect(onChange).not.toHaveBeenCalled();
    expect(document.body.style.userSelect).toBe("");
  });

  it("без нажатия движение ничего не меняет", () => {
    const { handle, onChange } = setup();
    fireEvent.pointerMove(handle, { clientX: 100 });
    expect(onChange).not.toHaveBeenCalled();
  });

  it("стрелки, Home и End", () => {
    const { handle, onChange } = setup(248);

    fireEvent.keyDown(handle, { key: "ArrowRight" });
    expect(onChange).toHaveBeenLastCalledWith(264);
    fireEvent.keyDown(handle, { key: "ArrowLeft" });
    expect(onChange).toHaveBeenLastCalledWith(232);
    fireEvent.keyDown(handle, { key: "Home" });
    expect(onChange).toHaveBeenLastCalledWith(64);
    fireEvent.keyDown(handle, { key: "End" });
    expect(onChange).toHaveBeenLastCalledWith(420);

    onChange.mockClear();
    fireEvent.keyDown(handle, { key: "a" });
    expect(onChange).not.toHaveBeenCalled();
  });

  it("двойной щелчок возвращает ширину по умолчанию", () => {
    const { handle, onReset } = setup(300);
    fireEvent.doubleClick(handle);
    expect(onReset).toHaveBeenCalledTimes(1);
  });
});
