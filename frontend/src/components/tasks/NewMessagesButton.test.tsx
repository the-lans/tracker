import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";
import { NewMessagesButton } from "@/components/tasks/NewMessagesButton";

describe("NewMessagesButton", () => {
  test("клик прокручивает ленту к концу", async () => {
    const onClick = vi.fn();
    render(<NewMessagesButton onClick={onClick} />);

    await userEvent.click(
      screen.getByRole("button", { name: "Новые сообщения" }),
    );

    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
