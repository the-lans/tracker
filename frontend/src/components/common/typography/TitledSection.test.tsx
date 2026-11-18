import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { TitledSection } from "@/components/common/typography/TitledSection";

describe("TitledSection", () => {
  test("заголовок и содержимое", () => {
    render(
      <TitledSection title="Описание">
        <p>Текст раздела</p>
      </TitledSection>,
    );

    expect(screen.getByText("Описание")).toBeInTheDocument();
    expect(screen.getByText("Текст раздела")).toBeInTheDocument();
  });
});
