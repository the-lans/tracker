import { Moon, Sun } from "lucide-react";
import { useTheme } from "@/hooks/useTheme";
import { cn } from "@/lib/utils";

export function ThemeToggle({ compact = false }: { compact?: boolean }) {
  const { theme, setTheme, toggleTheme } = useTheme();

  // В узком меню — одна кнопка: показывает текущую тему, нажатие переключает.
  if (compact) {
    const Icon = theme === "light" ? Sun : Moon;
    return (
      <button
        type="button"
        aria-label={theme === "light" ? "Включить тёмную тему" : "Включить светлую тему"}
        title={theme === "light" ? "Включить тёмную тему" : "Включить светлую тему"}
        onClick={toggleTheme}
        className="flex size-11 items-center justify-center rounded-full border border-border bg-surface-2 text-accent xl:size-8"
      >
        <Icon className="size-3.5" />
      </button>
    );
  }

  return (
    <div className="inline-flex items-center gap-0.5 self-start rounded-full border border-border bg-surface-2 p-[3px]">
      <button
        type="button"
        aria-label="Светлая тема"
        aria-pressed={theme === "light"}
        onClick={() => setTheme("light")}
        className={cn(
          "flex size-11 items-center justify-center rounded-full text-text-3 xl:size-8",
          theme === "light" && "bg-surface text-accent shadow-sm",
        )}
      >
        <Sun className="size-3.5" />
      </button>
      <button
        type="button"
        aria-label="Тёмная тема"
        aria-pressed={theme === "dark"}
        onClick={() => setTheme("dark")}
        className={cn(
          "flex size-11 items-center justify-center rounded-full text-text-3 xl:size-8",
          theme === "dark" && "bg-surface text-accent shadow-sm",
        )}
      >
        <Moon className="size-3.5" />
      </button>
    </div>
  );
}
