import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";
import { ScrollToBottomButton } from "@/components/tasks/ScrollToBottomButton";

describe("ScrollToBottomButton", () => {
  test("клик прокручивает ленту к концу", async () => {
    const onClick = vi.fn();
    render(<ScrollToBottomButton hasUnseen={false} onClick={onClick} />);

    await userEvent.click(screen.getByRole("button", { name: "Перейти в конец ленты" }));

    expect(onClick).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("unseen-dot")).not.toBeInTheDocument();
  });

  test("ниже появилось новое — точка и другая подпись", () => {
    render(<ScrollToBottomButton hasUnseen onClick={vi.fn()} />);

    expect(screen.getByRole("button", { name: "Новые сообщения — перейти в конец" })).toBeInTheDocument();
    expect(screen.getByTestId("unseen-dot")).toBeInTheDocument();
  });
});
