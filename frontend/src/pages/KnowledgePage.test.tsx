import { screen } from "@testing-library/react";
import { describe, expect } from "vitest";
import { KnowledgePage } from "@/pages/KnowledgePage";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const section = {id:"s1",name:"Общее",user_read:true,user_write:true};
const file = {id:"f1",path:"Карта.md",version:1,is_directory:false,deleted_at:null};

describe("KnowledgePage", () => {
  test("редактирование отправляет прочитанную версию", async ({api}) => {
    api.respond("GET /knowledge/sections",[section]);
    api.respond("GET /knowledge/sections/s1/entries",[file]);
    api.respond("GET /knowledge/entries/f1/content",{content:"Начало",version:1});
    api.respond("PUT /knowledge/sections/s1/entries",{...file,version:2});
    const {user}=renderWithProviders(<KnowledgePage />);
    await screen.findByRole("option",{name:"Общее"});
    await user.selectOptions(screen.getByRole("combobox"),"s1");
    await user.click(await screen.findByRole("button",{name:/Карта.md/}));
    const editor=await screen.findByLabelText("Содержимое файла");
    await user.type(editor," правка");
    await user.click(screen.getByRole("button",{name:"Сохранить"}));
    await expect.poll(() => api.mutations().some((r) => r.method==="PUT" && (r.body as {expected_version:number}).expected_version===1)).toBe(true);
  });
});
