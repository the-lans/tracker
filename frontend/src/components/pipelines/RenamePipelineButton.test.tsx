import { screen } from "@testing-library/react";
import { describe, expect } from "vitest";
import { RenamePipelineButton } from "@/components/pipelines/RenamePipelineButton";
import type { Pipeline } from "@/lib/types";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const pipeline: Pipeline = { id: "p1", name: "Старое имя", is_archived: false, created_by: "u1" };

describe("RenamePipelineButton", () => {
  test("новое название отправляется без пробелов по краям и закрывает окно", async ({ api, toasts }) => {
    api.respond("PATCH /pipelines/p1", { ...pipeline, name: "Новое имя" });
    const { user } = renderWithProviders(<RenamePipelineButton pipeline={pipeline} />);

    await user.click(screen.getByRole("button", { name: "Переименовать Старое имя" }));
    const input = screen.getByLabelText(/Название/);
    expect(input).toHaveValue("Старое имя");
    await user.clear(input);
    await user.type(input, "  Новое имя  ");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    await expect.poll(() => api.mutations()[0]?.body).toEqual({ name: "Новое имя" });
    expect(api.mutations()[0]?.path).toBe("/pipelines/p1");
    await expect.poll(() => toasts.success).toHaveBeenCalledWith("Пайплайн переименован");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  test("пустое и прежнее название сохранить нельзя", async () => {
    const { user } = renderWithProviders(<RenamePipelineButton pipeline={pipeline} />);

    await user.click(screen.getByRole("button", { name: "Переименовать Старое имя" }));
    const save = screen.getByRole("button", { name: "Сохранить" });
    expect(save).toBeDisabled();

    await user.clear(screen.getByLabelText(/Название/));
    expect(save).toBeDisabled();
    await user.type(screen.getByLabelText(/Название/), "   ");
    expect(save).toBeDisabled();
  });

  test("Enter сохраняет, ошибка сервера показывается и окно остаётся", async ({ api, toasts }) => {
    api.respond("PATCH /pipelines/p1", { error: { status: 422, message: "Некорректное название" } });
    const { user } = renderWithProviders(<RenamePipelineButton pipeline={pipeline} />);

    await user.click(screen.getByRole("button", { name: "Переименовать Старое имя" }));
    await user.type(screen.getByLabelText(/Название/), " 2{Enter}");

    await expect.poll(() => toasts.error).toHaveBeenCalledWith("Некорректное название");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  test("при повторном открытии — актуальное название, а не недописанная правка", async () => {
    const { user } = renderWithProviders(<RenamePipelineButton pipeline={pipeline} />);

    await user.click(screen.getByRole("button", { name: "Переименовать Старое имя" }));
    await user.type(screen.getByLabelText(/Название/), " черновик");
    await user.click(screen.getByRole("button", { name: "Отмена" }));
    await user.click(screen.getByRole("button", { name: "Переименовать Старое имя" }));

    expect(screen.getByLabelText(/Название/)).toHaveValue("Старое имя");
  });
});
