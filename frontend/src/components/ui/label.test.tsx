import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { Label } from "./label";

describe("Label", () => {
  test.for([
    { required: true, marked: true },
    { required: false, marked: false },
    { required: undefined, marked: false },
  ])("required=$required — звёздочка: $marked", ({ required, marked }) => {
    render(
      <>
        <Label htmlFor="field" required={required}>
          Название
        </Label>
        <input id="field" />
      </>,
    );

    const label = screen.getByText("Название");
    expect(label.hasAttribute("data-required")).toBe(marked);
    expect(label.className.includes("after:content-['*']")).toBe(marked);
    // Звёздочка не входит в текст подписи — поле находится по ней как раньше.
    expect(screen.getByLabelText("Название")).toBe(document.getElementById("field"));
  });
});
