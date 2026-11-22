import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import {
  Archive,
  CalendarCheck,
  LayoutGrid,
  GitBranch,
  BookText,
  Library,
  FileStack,
  FolderGit2,
  KeySquare,
  Variable,
  ShieldCheck,
  Activity,
  Bell,
  Tags,
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
  /** Подсвечивать только на самом адресе, а не на вложенных страницах. */
  end?: boolean;
  /** Меню схлопнуто до значков: подпись скрыта, остаётся в подсказке и имени ссылки. */
  compact?: boolean;
}

function NavItem({ to, label, icon: Icon, badge, end, compact }: NavItemDef) {
  return (
    <NavLink
      to={to}
      end={end}
      aria-label={compact ? label : undefined}
      title={compact ? label : undefined}
      className={({ isActive }) =>
        cn(
          "relative flex touch-target items-center rounded-md py-2 text-sm font-semibold text-text-2",
          compact ? "justify-center px-0" : "gap-[11px] px-2.5",
          isActive && "bg-accent-tint text-accent",
        )
      }
    >
      {({ isActive }) => (
        <>
          {isActive && (
            <span
              className={cn(
                "absolute top-2 bottom-2 w-[3px] rounded-full bg-accent",
                compact ? "-left-3" : "-left-3.5",
              )}
            />
          )}
          <Icon className="size-[18px] shrink-0" />
          {!compact && <span className="truncate">{label}</span>}
          <CountBadge
            count={badge}
            className={compact
                ? "absolute right-0 top-0 min-w-[18px] px-1 py-0 text-center text-[10px] leading-[18px]"
                : "ml-auto"}
          />
        </>
      )}
    </NavLink>
  );
}

/** Заголовок раздела меню; в режиме значков — просто разделитель. */
function NavSection({ title, compact, children }: { title: string; compact: boolean; children: ReactNode }) {
  return (
    <div className={cn("flex flex-col gap-0.5", compact ? "mt-3 border-t border-border pt-3" : "mt-4")}>
      {compact ? (
        <span className="sr-only">{title}</span>
      ) : (
        <div className="px-2.5 pb-1.5 pt-2.5 text-caption font-bold uppercase tracking-wider text-text-3">
          {title}
        </div>
      )}
      {children}
    </div>
  );
}

/** Логотип и название — шапка меню; в мобильной шторке она отдельно от прокручиваемого списка. */
export function SidebarBrand({ className, compact = false }: { className?: string; compact?: boolean }) {
  return (
    <div
      className={cn(
        "flex items-center px-2 pb-[22px] pt-1.5",
        compact ? "justify-center" : "gap-2.5",
        className,
      )}
    >
      <BrandMark />
      {!compact && <span className="text-title font-extrabold tracking-tight">Tracker</span>}
    </div>
  );
}

interface SidebarProps {
  onNavigate?: () => void;
  hideBrand?: boolean;
  /** Ширина меню на компьютере, px; без неё — как в мобильной шторке (на всю ширину) или по умолчанию. */
  width?: number;
  /** Только значки, без подписей. */
  compact?: boolean;
}

export function Sidebar({ onNavigate, hideBrand = false, width, compact = false }: SidebarProps) {
  const { user } = useAuth();
  const { data: awaitingCount } = useAwaitingDecisionCount();
  const side = compact ? "px-3" : "px-3.5";

  return (
    <aside
      aria-label="Основное меню"
      style={width === undefined ? undefined : { width }}
      className={cn(
        // Шапка и подвал закреплены, прокручивается только список разделов.
        "flex h-full min-h-0 shrink-0 flex-col overflow-hidden border-r border-border bg-surface",
        width === undefined && !hideBrand && "w-[248px]",
        hideBrand && "w-full border-r-0",
      )}
      onClick={onNavigate}
    >
      {!hideBrand && <SidebarBrand compact={compact} className={cn("shrink-0 pt-3.5", side)} />}

      <div className={cn("min-h-0 flex-1 overflow-y-auto overscroll-contain pb-3", side, hideBrand && "pt-1")}>
        <nav className="flex flex-col gap-0.5">
          <NavItem to="/" label="Дашборд" icon={LayoutGrid} badge={awaitingCount?.count} compact={compact} />
          <NavItem to="/daily" label="Дейли" icon={CalendarCheck} compact={compact} />
          <NavItem to="/categories" label="Категории" icon={Tags} compact={compact} />
          <NavItem to="/pipelines" label="Пайплайны" icon={GitBranch} compact={compact} />
          <NavItem to="/library" label="Библиотека промтов" icon={BookText} compact={compact} />
          <NavItem to="/knowledge" label="База знаний" icon={Library} compact={compact} />
          <NavItem to="/templates" label="Шаблоны" icon={FileStack} compact={compact} />
          <NavItem to="/repositories" label="Репозитории" icon={FolderGit2} compact={compact} />
          <NavItem to="/events" label="События" icon={Bell} compact={compact} />
          <NavItem to="/archive" label="Архив" icon={Archive} compact={compact} />
        </nav>

        <NavSection title="Настройки" compact={compact}>
          <NavItem to="/llm-accounts" label="LLM-аккаунты" icon={KeySquare} compact={compact} />
          {/* Раздел 1.2 п. 11, 15.1: переменные окружения ведёт администратор. */}
          {user?.role === UserRole.ADMIN && (
            <NavItem to="/env-variables" label="Переменные окружения" icon={Variable} compact={compact} />
          )}
        </NavSection>

        {user?.role === UserRole.ADMIN && (
          <NavSection title="Администрирование" compact={compact}>
            <NavItem to="/admin" label="Администрирование" icon={ShieldCheck} end compact={compact} />
            <NavItem to="/admin/monitoring" label="Мониторинг" icon={Activity} compact={compact} />
          </NavSection>
        )}
      </div>

      <div
        className={cn(
          "flex shrink-0 flex-col gap-2.5 border-t border-border py-3",
          compact ? "items-center px-3" : "px-3.5",
        )}
      >
        <ThemeToggle compact={compact} />
        <NavLink
          to="/profile"
          aria-label={compact ? `Профиль: ${user?.email ?? "—"}` : undefined}
          title={compact ? (user?.email ?? "Профиль") : undefined}
          className={cn("flex items-center rounded-md p-1", compact ? "justify-center" : "gap-2.5")}
        >
          <UserAvatar email={user?.email} />
          {!compact && (
            <div className="min-w-0">
              <div className="truncate text-body font-bold" title={user?.email}>{user?.email ?? "—"}</div>
              <div className="text-meta text-text-3">{user ? USER_ROLE_LABEL[user.role] : ""}</div>
            </div>
          )}
        </NavLink>
      </div>
    </aside>
  );
}
