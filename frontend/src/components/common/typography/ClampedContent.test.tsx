import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ClampedContent } from "@/components/common/typography/ClampedContent";

const original = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollHeight");

function setContentHeight(height: number) {
  Object.defineProperty(HTMLElement.prototype, "scrollHeight", { configurable: true, get: () => height });
}

afterEach(() => {
  if (original) Object.defineProperty(HTMLElement.prototype, "scrollHeight", original);
});

describe("ClampedContent", () => {
  it("длинное содержимое обрезается: есть затухание и действие под ним", () => {
    setContentHeight(600);
    render(
      <ClampedContent maxHeight={192} renderMore={() => <button>Открыть полностью</button>}>
        <p>Длинный текст</p>
      </ClampedContent>,
    );

    expect(screen.getByTestId("clamped-fade")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Открыть полностью" })).toBeInTheDocument();
    expect(screen.getByText("Длинный текст").parentElement?.parentElement).toHaveStyle({ maxHeight: "192px" });
  });

  it("короткое содержимое показывается целиком, без затухания и действия", () => {
    setContentHeight(100);
    render(
      <ClampedContent maxHeight={192} renderMore={() => <button>Открыть полностью</button>}>
        <p>Короткий текст</p>
      </ClampedContent>,
    );

    expect(screen.queryByTestId("clamped-fade")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
