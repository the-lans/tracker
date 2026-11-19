import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { MessageBubble } from "@/components/tasks/MessageBubble";

// Время в локальной зоне: тест не зависит от часового пояса машины.
const at = (hours: number, minutes: number) =>
  new Date(2026, 10, 10, hours, minutes).toISOString();

describe("MessageBubble: время реплики", () => {
  test("время — в правом нижнем углу, рядом с «Копировать» и «Скачать»", () => {
    render(<MessageBubble role="llm" text="Ответ" timestamp={at(15, 30)} />);

    const time = screen.getByText(/\d{2}:\d{2}/);
    expect(time.tagName).toBe("TIME");
    expect(time).toHaveAttribute("dateTime", at(15, 30));
    expect(time).toHaveAttribute("title", expect.stringMatching(/10\.11\.26/));
    expect(time.parentElement).toHaveClass("ml-auto");
    expect(time.parentElement?.parentElement).toContainElement(
      screen.getByRole("button", { name: /Копировать/ }),
    );
  });

  test.for([
    { name: "без времени", props: { timestamp: null } },
    { name: "время не передано", props: {} },
    {
      name: "реплика «думает…»",
      props: { thinking: true, timestamp: at(15, 30) },
    },
  ])("$name — времени нет", ({ props }) => {
    const { container } = render(
      <MessageBubble role="llm" text="Ответ" {...props} />,
    );

    expect(container.querySelector("time")).toBeNull();
  });

  test("реплика пользователя тоже со временем", () => {
    const { container } = render(
      <MessageBubble role="user" text="Промт" timestamp={at(9, 5)} />,
    );

    expect(container.querySelector("time")).toHaveAttribute(
      "dateTime",
      at(9, 5),
    );
  });
});
