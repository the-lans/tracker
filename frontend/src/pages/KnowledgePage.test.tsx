import { act, screen } from "@testing-library/react";
import { describe, expect } from "vitest";
import { KnowledgePage } from "@/pages/KnowledgePage";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const section = {id:"s1",name:"Общее",user_read:true,user_write:true};
const file = {id:"f1",path:"Карта.md",version:1,is_directory:false,deleted_at:null};

describe("KnowledgePage", () => {
  test("выбор папки и создание вложенной папки не запрашивают её как файл", async ({api}) => {
    const directory = {...file, id:"d1", path:"Документы", is_directory:true};
    api.respond("GET /knowledge/sections", [section]);
    api.respond("GET /knowledge/sections/s1/entries", [directory]);
    api.respond("PUT /knowledge/sections/s1/entries", {...directory, id:"d2", path:"Документы/Инструкции"});
    const {user} = renderWithProviders(<KnowledgePage />);
    await user.click(await screen.findByRole("combobox", {name:"Раздел"}));
    await user.click(await screen.findByRole("option", {name:"Общее"}));
    await user.click(await screen.findByRole("button", {name:"Документы"}));
    expect(api.requests.some((request) => request.path === "/knowledge/entries/d1/content")).toBe(false);
    expect(screen.queryByLabelText("Содержимое файла")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", {name:"Новая папка"}));
    expect(screen.getByLabelText("Путь файла")).toHaveValue("Документы/");
    await user.type(screen.getByLabelText("Путь файла"), "Инструкции");
    await user.click(screen.getByRole("button", {name:"Создать папку"}));
    await expect.poll(() => api.mutations().some((request) => request.method === "PUT" && (request.body as {path:string; is_directory:boolean}).path === "Документы/Инструкции" && (request.body as {is_directory:boolean}).is_directory)).toBe(true);
    expect(await screen.findByText("Папка: Документы/Инструкции")).toBeInTheDocument();
    await user.upload(screen.getByLabelText("Загрузить файл"), new File(["текст"], "Карта.txt", {type:"text/plain"}));
    await expect.poll(() => api.queriesOf("POST /knowledge/sections/s1/upload")).toEqual([{path:"Документы/Инструкции/Карта.txt"}]);
    await user.click(screen.getByRole("button", {name:"Новый файл"}));
    expect(screen.getByLabelText("Путь файла")).toHaveValue("Документы/Инструкции/");
  });

  test("поиск не предлагает создать существующую карту", async ({api}) => {
    api.respond("GET /knowledge/sections", [section]);
    api.respond("GET /knowledge/sections/s1/entries", [file, {...file, id:"map", path:"README.md"}]);
    api.respond("GET /knowledge/sections/s1/search", [file]);
    const {user} = renderWithProviders(<KnowledgePage />);
    await user.click(await screen.findByRole("combobox", {name:"Раздел"}));
    await user.click(await screen.findByRole("option", {name:"Общее"}));
    await screen.findByRole("button", {name:/README.md/});
    await user.type(screen.getByRole("textbox", {name:"Поиск файлов"}), "Карта");
    await expect.poll(() => api.queriesOf("GET /knowledge/sections/s1/search").length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", {name:"Создать карту ресурсов"})).not.toBeInTheDocument();
  });

  test("запоздавшее создание папки не меняет новый выбор", async ({api}) => {
    let finish!: (value: unknown) => void;
    const directory = {...file, id:"d1", path:"Другая", is_directory:true};
    api.respond("GET /knowledge/sections", [section]);
    api.respond("GET /knowledge/sections/s1/entries", [directory]);
    api.respond("PUT /knowledge/sections/s1/entries", () => new Promise((resolve) => { finish = resolve; }));
    const {user} = renderWithProviders(<KnowledgePage />);
    await user.click(await screen.findByRole("combobox", {name:"Раздел"}));
    await user.click(await screen.findByRole("option", {name:"Общее"}));
    await user.click(screen.getByRole("button", {name:"Новая папка"}));
    await user.type(screen.getByLabelText("Путь файла"), "Новая");
    await user.click(screen.getByRole("button", {name:"Создать папку"}));
    await user.click(await screen.findByRole("button", {name:"Другая"}));
    await act(async () => { finish({...directory, id:"d2", path:"Новая"}); });
    expect(screen.getByText("Папка: Другая")).toBeInTheDocument();
    expect(screen.getByText("Выбрана папка: Другая")).toBeInTheDocument();
  });

  test("удалённую карту можно открыть в корзине и восстановить", async ({api}) => {
    const deletedMap = {...file, id:"map", path:"README.md", version:2, deleted_at:"2026-01-01"};
    api.respond("GET /knowledge/sections", [section]);
    api.respond("GET /knowledge/sections/s1/entries", [deletedMap]);
    api.respond("GET /knowledge/entries/map/content", {content:"Карта", version:2});
    const {user} = renderWithProviders(<KnowledgePage />);
    await user.click(await screen.findByRole("combobox", {name:"Раздел"}));
    await user.click(await screen.findByRole("option", {name:"Общее"}));
    await user.click(await screen.findByRole("button", {name:"Найти README.md в корзине"}));
    expect(screen.getByRole("checkbox", {name:"Корзина"})).toBeChecked();
    await user.click(await screen.findByRole("button", {name:"Восстановить"}));
    await expect.poll(() => api.mutations().find((request) => request.path === "/knowledge/entries/map/deleted")?.body).toEqual({expected_version:2, deleted:false});
    expect(api.mutations().some((request) => request.method === "PUT")).toBe(false);
  });

  test("загрузка использует выбранную папку", async ({api}) => {
    api.respond("GET /knowledge/sections", [section]);
    api.respond("GET /knowledge/sections/s1/entries", [{...file, id:"d1", path:"Документы", is_directory:true}]);
    const {user} = renderWithProviders(<KnowledgePage />);
    await user.click(await screen.findByRole("combobox", {name:"Раздел"}));
    await user.click(await screen.findByRole("option", {name:"Общее"}));
    await user.click(await screen.findByRole("button", {name:"Документы"}));
    await user.upload(screen.getByLabelText("Загрузить файл"), new File(["текст"], "Карта.txt", {type:"text/plain"}));
    await expect.poll(() => api.queriesOf("POST /knowledge/sections/s1/upload")).toEqual([{path:"Документы/Карта.txt"}]);
  });

  test("историческая версия сохраняется как новая с проверкой текущей версии", async ({api}) => {
    api.respond("GET /knowledge/sections", [section]);
    api.respond("GET /knowledge/sections/s1/entries", [{...file, version:2}]);
    api.respond("GET /knowledge/entries/f1/content", {content:"Текущая", version:2});
    api.respond("GET /knowledge/entries/f1/history", [{version:1, created_at:"2026-01-01T00:00:00Z", created_by:"u1", task_id:null}]);
    api.respond("PUT /knowledge/sections/s1/entries", {...file, version:3});
    const {user} = renderWithProviders(<KnowledgePage />);
    await user.click(await screen.findByRole("combobox", {name:"Раздел"}));
    await user.click(await screen.findByRole("option", {name:"Общее"}));
    await user.click(await screen.findByRole("button", {name:/Карта.md/}));
    await screen.findByDisplayValue("Текущая");
    api.respond("GET /knowledge/entries/f1/content", {content:"Старая", version:1});
    await user.click(screen.getByText("История изменений"));
    await user.click(await screen.findByRole("button", {name:"Открыть версию"}));
    expect(await screen.findByText(/Открыта версия 1/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", {name:"Сохранить"}));
    await expect.poll(() => api.mutations().find((request) => request.method === "PUT")?.body).toMatchObject({content:"Старая", expected_version:2});
  });
  test("корзина переключает список удалённых файлов", async ({api}) => {
    api.respond("GET /knowledge/sections",[section]);
    api.respond("GET /knowledge/sections/s1/entries",[file, {...file, id:"f2", path:"Удалённый.md", deleted_at:"2026-01-01"}]);
    const {user}=renderWithProviders(<KnowledgePage />);
    await user.click(await screen.findByRole("combobox",{name:"Раздел"}));
    await user.click(await screen.findByRole("option",{name:"Общее"}));
    expect(await screen.findByRole("button",{name:/Карта.md/})).toBeInTheDocument();
    await user.click(screen.getByRole("checkbox",{name:"Корзина"}));
    expect(screen.getByRole("button",{name:/Удалённый.md/})).toBeInTheDocument();
    expect(screen.queryByRole("button",{name:/Карта.md/})).not.toBeInTheDocument();
    await user.click(screen.getByRole("checkbox",{name:"Корзина"}));
    expect(await screen.findByRole("button",{name:/Карта.md/})).toBeInTheDocument();
  });
  test("редактирование отправляет прочитанную версию", async ({api}) => {
    api.respond("GET /knowledge/sections",[section]);
    api.respond("GET /knowledge/sections/s1/entries",[file]);
    api.respond("GET /knowledge/entries/f1/content",{content:"Начало",version:1});
    api.respond("PUT /knowledge/sections/s1/entries",{...file,version:2});
    const {user}=renderWithProviders(<KnowledgePage />);
    await user.click(await screen.findByRole("combobox",{name:"Раздел"}));
    await user.click(await screen.findByRole("option",{name:"Общее"}));
    await user.click(await screen.findByRole("button",{name:/Карта.md/}));
    const editor=await screen.findByLabelText("Содержимое файла");
    await user.type(editor," правка");
    await user.click(screen.getByRole("button",{name:"Сохранить"}));
    await expect.poll(() => api.mutations().some((r) => r.method==="PUT" && (r.body as {expected_version:number}).expected_version===1)).toBe(true);
  });
  test("сохранение недоступно до завершения чтения", async ({api}) => {
    let finishRead!: (value: unknown) => void;
    api.respond("GET /knowledge/sections",[section]);
    api.respond("GET /knowledge/sections/s1/entries",[file]);
    api.respond("GET /knowledge/entries/f1/content", () => new Promise((resolve) => { finishRead = resolve; }));
    const {user}=renderWithProviders(<KnowledgePage />);
    await user.click(await screen.findByRole("combobox",{name:"Раздел"}));
    await user.click(await screen.findByRole("option",{name:"Общее"}));
    await user.click(await screen.findByRole("button",{name:/Карта.md/}));
    expect(screen.getByLabelText("Содержимое файла")).toBeDisabled();
    expect(screen.getByRole("button",{name:"Сохранить"})).toBeDisabled();
    await act(async () => { finishRead({content:"Исходный текст",version:1}); });
    expect(await screen.findByDisplayValue("Исходный текст")).not.toBeDisabled();
  });

});
