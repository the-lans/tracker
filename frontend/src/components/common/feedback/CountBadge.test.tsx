import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CountBadge } from "@/components/common/feedback/CountBadge";

describe("CountBadge", () => {
  it("при нуле и без числа ничего не показывает", () => {
    const { container, rerender } = render(<CountBadge count={0} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<CountBadge />);
    expect(container).toBeEmptyDOMElement();
  });

  it("показывает число как есть, пока оно не больше предела", () => {
    const { rerender } = render(<CountBadge count={99} max={99} />);
    expect(screen.getByText("99")).toBeInTheDocument();
    rerender(<CountBadge count={7} />);
    expect(screen.getByText("7")).toBeInTheDocument();
  });

  it("выше предела — «99+», чтобы кружок не раздувался", () => {
    render(<CountBadge count={128} max={99} />);
    expect(screen.getByText("99+")).toBeInTheDocument();
  });

  it("без предела большое число показывается целиком", () => {
    render(<CountBadge count={128} />);
    expect(screen.getByText("128")).toBeInTheDocument();
  });
});
