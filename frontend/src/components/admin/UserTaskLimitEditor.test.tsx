import { screen } from "@testing-library/react";
import { describe, expect } from "vitest";
import { UserTaskLimitEditor } from "@/components/admin/UserTaskLimitEditor";
import { makeUser } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const USER = makeUser({ id: "u2", max_parallel_tasks: 3 });
const field = () => screen.getByRole("spinbutton", { name: `Параллельных задач ${USER.email}` });

describe("UserTaskLimitEditor", () => {
  test.for([
    { input: "5{Enter}", body: { max_parallel_tasks: 5 } },
    { input: "50{Enter}", body: { max_parallel_tasks: 50 } },
    { input: "1{Enter}", body: { max_parallel_tasks: 1 } },
    { input: "0{Enter}", body: null },
    { input: "51{Enter}", body: null },
    { input: "3{Enter}", body: null },
    { input: "7{Escape}", body: null },
  ])("«$input» → $body", async ({ input, body }, { api }) => {
    const { user } = renderWithProviders(<UserTaskLimitEditor user={USER} />);

    await user.clear(field());
    await user.type(field(), input);

    expect(api.mutations()).toEqual(body ? [{ method: "PATCH", path: "/users/u2", body }] : []);
  });

  test("Escape отменяет правку — уход с поля ничего не сохраняет", async ({ api }) => {
    const { user } = renderWithProviders(<UserTaskLimitEditor user={makeUser({ id: "u2" })} />);

    await user.clear(field());
    await user.type(field(), "8{Escape}");
    await user.tab();

    expect(api.mutations()).toEqual([]);
    expect(field()).toHaveValue(3);
  });

  test("сохраняется и по уходу с поля", async ({ api }) => {
    const { user } = renderWithProviders(<UserTaskLimitEditor user={makeUser({ id: "u2" })} />);

    await user.clear(field());
    await user.type(field(), "8");
    await user.tab();

    expect(api.mutations()).toEqual([{ method: "PATCH", path: "/users/u2", body: { max_parallel_tasks: 8 } }]);
  });
});
