import { screen } from "@testing-library/react";
import { useLocation } from "react-router-dom";
import { describe, expect } from "vitest";
import { PageTabs } from "@/components/common/navigation/PageTabs";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const TABS = [
  { value: "first", label: "Первая", content: <div>содержимое первой</div> },
  { value: "second", label: "Вторая", content: <div>содержимое второй</div> },
];

function LocationProbe() {
  return <div data-testid="location">{useLocation().search}</div>;
}

function renderTabs(path: string) {
  return renderWithProviders(
    <>
      <PageTabs tabs={TABS} />
      <LocationProbe />
    </>,
    { path },
  );
}

describe("PageTabs", () => {
  test.for([
    { path: "/", shown: "содержимое первой" },
    { path: "/?tab=second", shown: "содержимое второй" },
    { path: "/?tab=unknown", shown: "содержимое первой" },
  ])("$path → «$shown»", ({ path, shown }) => {
    renderTabs(path);

    expect(screen.getByText(shown)).toBeVisible();
  });

  test("выбранная вкладка попадает в адрес", async () => {
    const { user } = renderTabs("/");

    await user.click(screen.getByRole("tab", { name: "Вторая" }));

    expect(screen.getByText("содержимое второй")).toBeVisible();
    expect(screen.getByTestId("location")).toHaveTextContent("?tab=second");
  });
});
