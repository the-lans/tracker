import { useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { Menu } from "lucide-react";
import { Sidebar, SidebarBrand } from "@/components/layout/Sidebar";
import { SidebarResizer } from "@/components/layout/SidebarResizer";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { CountBadge } from "@/components/common/feedback/CountBadge";
import { useAwaitingDecisionCount } from "@/hooks/useTasks";
import { useSidebarWidth } from "@/hooks/useSidebarWidth";
import { ensurePushSubscription } from "@/lib/push";

const TITLES: Record<string, string> = {
  "/": "Дашборд",
  "/daily": "Дейли",
  "/pipelines": "Пайплайны",
  "/knowledge": "База знаний",
  "/library": "Библиотека промтов",
  "/categories": "Категории",
  "/templates": "Шаблоны",
  "/repositories": "Репозитории",
  "/events": "События",
  "/archive": "Архив",
  "/llm-accounts": "LLM-аккаунты",
  "/env-variables": "Переменные окружения",
  "/profile": "Профиль",
  "/admin": "Администрирование",
  "/admin/monitoring": "Мониторинг",
};

export function AppShell() {
  const location = useLocation();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const { data: awaitingCount } = useAwaitingDecisionCount();
  const sidebar = useSidebarWidth();

  useEffect(() => {
    // Раздел 18.1: "подписка запрашивается при первом входе" — AppShell
    // монтируется один раз на всю аутентифицированную сессию (обёрнут
    // вокруг всех защищённых маршрутов), поэтому это и есть точка первого
    // входа, а не каждая отдельная страница.
    void ensurePushSubscription();
  }, []);

  return (
    <div className="flex h-dvh w-full overflow-hidden bg-bg text-text">
      {/* Ширину меню на компьютере меняют за правую границу; в шторке телефона она фиксирована. */}
      <div className="relative hidden shrink-0 lg:block" style={{ width: sidebar.width }}>
        <Sidebar width={sidebar.width} compact={sidebar.compact} />
        <SidebarResizer width={sidebar.width} onChange={sidebar.setWidth} onReset={sidebar.reset} />
      </div>

      <Sheet open={mobileNavOpen} onOpenChange={setMobileNavOpen}>
        <SheetContent
          className="left-0 top-0 flex h-dvh max-h-dvh w-[280px] max-w-[85vw] flex-col overflow-hidden rounded-none border-r border-t-0 p-0 [&>[data-sheet-handle]]:hidden"
          // Крестик — в шапке шторки, а не поверх полосы прокрутки меню.
          closeClassName="right-2 top-2"
        >
          <SheetTitle className="sr-only">Основное меню</SheetTitle>
          <SidebarBrand className="shrink-0 border-b border-border px-5 pb-3 pt-3.5" />
          <div className="min-h-0 flex-1">
            <Sidebar hideBrand onNavigate={() => setMobileNavOpen(false)} />
          </div>
        </SheetContent>
      </Sheet>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-4 border-b border-border bg-surface px-4 py-0.5 short:py-0 lg:hidden">
          {/* Раздел 18.3: счётчик ожидающих решения виден и без открытого меню. */}
          <Button
            variant="ghost"
            size="icon"
            // Кнопка ниже шапки по высоте, а зона нажатия — прежние 44px (touch-hit).
            className="touch-hit relative h-9 w-9 min-h-0! min-w-0!"
            aria-label={
              awaitingCount?.count
                ? `Меню, ожидают решения: ${awaitingCount.count}`
                : "Меню"
            }
            onClick={() => setMobileNavOpen(true)}
          >
            <Menu className="size-5" />
            <CountBadge count={awaitingCount?.count} className="absolute left-5 top-0" />
          </Button>
          <h1 className="text-title font-extrabold">
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
