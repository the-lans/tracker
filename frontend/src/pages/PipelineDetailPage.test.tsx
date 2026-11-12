import { screen } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { describe, expect } from "vitest";
import { PipelineDetailPage } from "@/pages/PipelineDetailPage";
import { NodeType } from "@/lib/types";
import { makeNode } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const review = makeNode({ id: "lib-review", pipeline_id: null, is_library_item: true, name: "Ревью" });

describe("PipelineDetailPage", () => {
  test.for([
    { library_node_id: null, type: "Слэш-команда", source: null },
    { library_node_id: "lib-review", type: "Промт из библиотеки", source: "Ревью" },
    { library_node_id: "lib-gone", type: "Промт из библиотеки", source: "недоступный промт" },
  ])("нода $library_node_id → тип «$type»", async ({ library_node_id, type, source }, { api }) => {
    api.respond("GET /pipelines/p1", { id: "p1", name: "Ревью кода" });
    api.respond("GET /pipelines/p1/nodes", [
      makeNode({ id: "n1", name: "Шаг", node_type: NodeType.SLASH_COMMAND, library_node_id }),
    ]);
    api.respond("GET /nodes", [review]);
    renderWithProviders(
      <Routes>
        <Route path="/pipelines/:pipelineId" element={<PipelineDetailPage />} />
      </Routes>,
      { path: "/pipelines/p1" },
    );

    expect(await screen.findByText(type)).toBeInTheDocument();
    if (source) expect(await screen.findByText(source)).toBeInTheDocument();
  });
});
