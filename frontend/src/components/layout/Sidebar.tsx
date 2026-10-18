import { NavLink } from "react-router-dom";
import {
  LayoutGrid,
  GitBranch,
  BookText,
  FileStack,
  FolderGit2,
  KeySquare,
  Variable,
  ShieldCheck,
} from "lucide-react";
import { BrandMark } from "@/components/layout/BrandMark";
import { ThemeToggle } from "@/components/layout/ThemeToggle";
import { useAuth } from "@/stores/authStore";
import { useAwaitingDecisionCount } from "@/hooks/useTasks";
import { initialsFromEmail } from "@/lib/utils";
import { UserRole } from "@/lib/types";
import { cn } from "@/lib/utils";

interface NavItemDef {
  to: string;
  label: string;
  icon: typeof LayoutGrid;
  badge?: number;
}

function NavItem({ to, label, icon: Icon, badge }: NavItemDef) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        cn(
          "relative flex touch-target items-center gap-[11px] rounded-md px-2.5 py-2 text-sm font-semibold text-text-2",
          isActive && "bg-accent-tint text-accent",
        )
      }
    >
      {({ isActive }) => (
        <>
          {isActive && (
            <span className="absolute -left-3.5 top-2 bottom-2 w-[3px] rounded-full bg-accent" />
          )}
          <Icon className="size-[18px] shrink-0" />
          <span className="truncate">{label}</span>
          {Boolean(badge) && (
            <span className="ml-auto rounded-full bg-danger px-[7px] py-px text-[11px] font-bold text-white">
              {badge}
            </span>
          )}
        </>
      )}
    </NavLink>
  );
}

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { user } = useAuth();
  const { data: awaitingCount } = useAwaitingDecisionCount();

  return (
    <aside
      className="flex h-full w-[248px] shrink-0 flex-col border-r border-border bg-surface p-3.5"
      onClick={onNavigate}
    >
      <div className="flex items-center gap-2.5 px-2 pb-[22px] pt-1.5">
        <BrandMark />
        <span className="text-[16px] font-extrabold tracking-tight">Tracker</span>
      </div>

      <nav className="flex flex-col gap-0.5">
        <NavItem to="/" label="Дашборд" icon={LayoutGrid} badge={awaitingCount?.count} />
        <NavItem to="/pipelines" label="Пайплайны" icon={GitBranch} />
        <NavItem to="/library" label="Библиотека промтов" icon={BookText} />
        <NavItem to="/templates" label="Шаблоны" icon={FileStack} />
        <NavItem to="/repositories" label="Репозитории" icon={FolderGit2} />
      </nav>

      <div className="mb-4.5 mt-4 flex flex-col gap-0.5">
        <div className="px-2.5 pb-1.5 pt-2.5 text-[11px] font-bold uppercase tracking-wider text-text-3">
          Настройки
        </div>
        <NavItem to="/llm-accounts" label="LLM-аккаунты" icon={KeySquare} />
        <NavItem to="/env-variables" label="Переменные окружения" icon={Variable} />
      </div>

      {user?.role === UserRole.ADMIN && (
        <div className="flex flex-col gap-0.5">
          <div className="px-2.5 pb-1.5 pt-2.5 text-[11px] font-bold uppercase tracking-wider text-text-3">
            Администрирование
          </div>
          <NavItem to="/admin" label="Администрирование" icon={ShieldCheck} />
        </div>
      )}

      <div className="mt-auto flex flex-col gap-2.5 border-t border-border pt-3">
        <ThemeToggle />
        <NavLink to="/profile" className="flex items-center gap-2.5 rounded-md p-1">
          <div className="relative flex size-[34px] shrink-0 items-center justify-center overflow-hidden rounded-full bg-gradient-to-br from-[#4f5fe0] to-[#8b5cf0] text-[13.5px] font-extrabold text-white">
            {user ? initialsFromEmail(user.email) : "?"}
          </div>
          <div className="min-w-0">
            <div className="truncate text-[13px] font-bold">{user?.email ?? "—"}</div>
            <div className="text-[11.5px] text-text-3">{user?.role ?? ""}</div>
          </div>
        </NavLink>
      </div>
    </aside>
  );
}
