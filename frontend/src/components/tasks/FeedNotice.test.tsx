import { render, screen } from "@testing-library/react";
import { Bell } from "lucide-react";
import { describe, expect, test } from "vitest";
import { FeedNotice } from "@/components/tasks/FeedNotice";

describe("FeedNotice", () => {
  test("по умолчанию — служебное событие с текстом", () => {
    render(<FeedNotice icon={Bell}>Контекст задачи сброшен</FeedNotice>);

    expect(screen.getByRole("note")).toHaveTextContent(
      "Контекст задачи сброшен",
    );
  });

  test("граница дат — разделитель", () => {
    render(
      <FeedNotice icon={Bell} role="separator">
        19 ноября
      </FeedNotice>,
    );

    expect(screen.getByRole("separator")).toHaveTextContent("19 ноября");
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });
});
