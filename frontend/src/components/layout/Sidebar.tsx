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
import { useAuth } from "@/hooks/useAuth";
import { useAwaitingDecisionCount } from "@/hooks/useTasks";
import { UserRole } from "@/lib/types";
import { cn } from "@/lib/utils";
import { USER_ROLE_LABEL } from "@/lib/labels";
import { UserAvatar } from "@/components/common/avatar/UserAvatar";
import { CountBadge } from "@/components/common/feedback/CountBadge";

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
          <CountBadge count={badge} className="ml-auto" />
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
        <span className="text-title font-extrabold tracking-tight">Tracker</span>
      </div>

      <nav className="flex flex-col gap-0.5">
        <NavItem to="/" label="Дашборд" icon={LayoutGrid} badge={awaitingCount?.count} />
        <NavItem to="/pipelines" label="Пайплайны" icon={GitBranch} />
        <NavItem to="/library" label="Библиотека промтов" icon={BookText} />
        <NavItem to="/templates" label="Шаблоны" icon={FileStack} />
        <NavItem to="/repositories" label="Репозитории" icon={FolderGit2} />
      </nav>

      <div className="mb-4.5 mt-4 flex flex-col gap-0.5">
        <div className="px-2.5 pb-1.5 pt-2.5 text-caption font-bold uppercase tracking-wider text-text-3">
          Настройки
        </div>
        <NavItem to="/llm-accounts" label="LLM-аккаунты" icon={KeySquare} />
        {/* Раздел 1.2 п. 11, 15.1: переменные окружения ведёт администратор. */}
        {user?.role === UserRole.ADMIN && (
          <NavItem to="/env-variables" label="Переменные окружения" icon={Variable} />
        )}
      </div>

      {user?.role === UserRole.ADMIN && (
        <div className="flex flex-col gap-0.5">
          <div className="px-2.5 pb-1.5 pt-2.5 text-caption font-bold uppercase tracking-wider text-text-3">
            Администрирование
          </div>
          <NavItem to="/admin" label="Администрирование" icon={ShieldCheck} />
        </div>
      )}

      <div className="mt-auto flex flex-col gap-2.5 border-t border-border pt-3">
        <ThemeToggle />
        <NavLink to="/profile" className="flex items-center gap-2.5 rounded-md p-1">
          <UserAvatar email={user?.email} />
          <div className="min-w-0">
            <div className="truncate text-body font-bold" title={user?.email}>{user?.email ?? "—"}</div>
            <div className="text-meta text-text-3">{user ? USER_ROLE_LABEL[user.role] : ""}</div>
          </div>
        </NavLink>
      </div>
    </aside>
  );
}
