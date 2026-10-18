import { useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { Menu } from "lucide-react";
import { Sidebar } from "@/components/layout/Sidebar";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { ensurePushSubscription } from "@/lib/push";

const TITLES: Record<string, string> = {
  "/": "Дашборд",
  "/pipelines": "Пайплайны",
  "/library": "Библиотека промтов",
  "/templates": "Шаблоны",
  "/repositories": "Репозитории",
  "/llm-accounts": "LLM-аккаунты",
  "/env-variables": "Переменные окружения",
  "/profile": "Профиль",
  "/admin": "Администрирование",
};

export function AppShell() {
  const location = useLocation();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  useEffect(() => {
    // Раздел 18.1: "подписка запрашивается при первом входе" — AppShell
    // монтируется один раз на всю аутентифицированную сессию (обёрнут
    // вокруг всех защищённых маршрутов), поэтому это и есть точка первого
    // входа, а не каждая отдельная страница.
    void ensurePushSubscription();
  }, []);

  return (
    <div className="flex h-dvh w-full overflow-hidden bg-bg text-text">
      <div className="hidden lg:block">
        <Sidebar />
      </div>

      <Sheet open={mobileNavOpen} onOpenChange={setMobileNavOpen}>
        <SheetContent className="left-0 top-0 h-dvh w-[280px] max-w-[85vw] rounded-none border-r border-t-0 p-0">
          <Sidebar onNavigate={() => setMobileNavOpen(false)} />
        </SheetContent>
      </Sheet>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-border bg-surface px-4 py-3 lg:hidden">
          <Button variant="ghost" size="icon" onClick={() => setMobileNavOpen(true)}>
            <Menu className="size-5" />
          </Button>
          <h1 className="text-[16px] font-extrabold">
            {TITLES[location.pathname] ?? "Tracker"}
          </h1>
        </header>
        <main className="min-h-0 flex-1 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
