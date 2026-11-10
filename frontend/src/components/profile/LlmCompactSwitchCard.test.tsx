import { screen } from "@testing-library/react";
import { describe, expect } from "vitest";
import { LlmCompactSwitchCard } from "@/components/profile/LlmCompactSwitchCard";
import { makeUser } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

describe("LlmCompactSwitchCard", () => {
  test.for([true, false])("переключатель %s меняется на противоположный", async (enabled, { api }) => {
    api.respond("GET /profile", makeUser({ llm_compact_on_switch: enabled }));
    api.respond("PUT /profile/llm-compact", makeUser({ llm_compact_on_switch: !enabled }));
    const { user } = renderWithProviders(<LlmCompactSwitchCard />);

    const toggle = await screen.findByRole("switch", { name: "Сжимать контекст при смене LLM-аккаунта" });
    expect(toggle).toHaveAttribute("aria-checked", String(enabled));
    await user.click(toggle);

    expect(api.mutations()).toEqual([
      { method: "PUT", path: "/profile/llm-compact", body: { enabled: !enabled } },
    ]);
    expect(await screen.findByRole("switch")).toHaveAttribute("aria-checked", String(!enabled));
  });
});
