import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";
import { IntegerSettingField } from "@/components/common/inputs/IntegerSettingField";
import { parseIntegerInRange } from "@/lib/integerInput";

function renderField(draft: string, onChange = vi.fn()) {
  render(
    <IntegerSettingField
      id="limit"
      label="Порог, %"
      draft={draft}
      parsed={parseIntegerInRange(draft, 1, 100)}
      min={1}
      max={100}
      hint="Сколько процентов"
      onChange={onChange}
    />,
  );
  return onChange;
}

describe("IntegerSettingField", () => {
  test("верное значение — подсказка", () => {
    renderField("98");

    expect(screen.getByLabelText("Порог, %")).toHaveValue(98);
    expect(screen.getByText("Сколько процентов")).toBeInTheDocument();
    expect(screen.getByLabelText("Порог, %")).toHaveAttribute(
      "aria-invalid",
      "false",
    );
  });

  test("значение вне границ — подсказка о границах и aria-invalid", () => {
    renderField("500");

    expect(screen.getByText("Целое число от 1 до 100")).toBeInTheDocument();
    expect(screen.queryByText("Сколько процентов")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Порог, %")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
  });

  test("ввод передаёт черновик наружу", async () => {
    const onChange = renderField("98");

    await userEvent.type(screen.getByLabelText("Порог, %"), "5");

    expect(onChange).toHaveBeenCalledWith("985");
  });
});
