import { render, screen } from "@testing-library/react";
import { describe, expect } from "vitest";
import { QueryState } from "@/components/common/feedback/QueryState";
import { test } from "@/test/fixtures";

describe("QueryState", () => {
  test.for([
    { isLoading: true, isError: false, shown: "Загрузка…" },
    { isLoading: false, isError: true, shown: "Сбой списка" },
    { isLoading: false, isError: false, shown: "содержимое" },
  ])("загрузка $isLoading, сбой $isError → «$shown»", ({ isLoading, isError, shown }) => {
    render(
      <QueryState isLoading={isLoading} isError={isError} errorLabel="Сбой списка">
        содержимое
      </QueryState>,
    );

    expect(screen.getByText(shown)).toBeInTheDocument();
    expect(screen.queryByText("содержимое") !== null).toBe(shown === "содержимое");
  });
});
