import { screen } from "@testing-library/react";
import { describe, expect } from "vitest";
import { NodeReorderButton } from "@/components/nodes/NodeReorderButton";
import { makeNode } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const plan = makeNode({ id: "n1", name: "План", order_index: 1 });
const tests = makeNode({ id: "n2", name: "Тесты", order_index: 2 });

describe("NodeReorderButton", () => {
  test.for([
    { direction: "up" as const, name: "Переместить выше: Тесты", node: tests, neighbor: plan },
    { direction: "down" as const, name: "Переместить ниже: План", node: plan, neighbor: tests },
  ])("«$name» меняет ноды местами", async ({ direction, name, node, neighbor }, { api }) => {
    api.respond(`PATCH /nodes/${node.id}`, node);
    api.respond(`PATCH /nodes/${neighbor.id}`, neighbor);
    const { user } = renderWithProviders(<NodeReorderButton node={node} neighbor={neighbor} direction={direction} />);

    await user.click(screen.getByRole("button", { name }));

    await expect
      .poll(() => api.mutations().map((request) => [request.path, request.body]))
      .toEqual([
        [`/nodes/${node.id}`, { order_index: neighbor.order_index }],
        [`/nodes/${neighbor.id}`, { order_index: node.order_index }],
      ]);
  });

  test("без соседа кнопка неактивна", () => {
    renderWithProviders(<NodeReorderButton node={plan} direction="up" />);

    expect(screen.getByRole("button", { name: "Переместить выше: План" })).toBeDisabled();
  });
});
