import { describe, expect, it } from "vitest";
import { isAgentTurn } from "@/components/tasks/messageKinds";
import { NodeType } from "@/lib/types";
import { makeNodeLog } from "@/test/factories";

const NODE_TYPES = new Map<string, NodeType>([
  ["prompt", NodeType.PLAIN_PROMPT],
  ["slash", NodeType.SLASH_COMMAND],
  ["plan", NodeType.PLAN_PROMPT],
  ["script", NodeType.SCRIPT],
  ["clear", NodeType.CLEAR_CONTEXT],
]);

describe("isAgentTurn", () => {
  it.each([
    { nodeId: null, agent: true },
    { nodeId: "prompt", agent: true },
    { nodeId: "slash", agent: true },
    { nodeId: "plan", agent: true },
    { nodeId: "script", agent: false },
    { nodeId: "clear", agent: false },
    { nodeId: "unknown", agent: false },
  ])("нода $nodeId → ход агента: $agent", ({ nodeId, agent }) => {
    expect(isAgentTurn(makeNodeLog({ node_id: nodeId }), NODE_TYPES)).toBe(agent);
  });
});
