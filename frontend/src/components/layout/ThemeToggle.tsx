import { Moon, Sun } from "lucide-react";
import { useTheme } from "@/stores/themeStore";
import { cn } from "@/lib/utils";

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();

  return (
    <div className="inline-flex items-center gap-0.5 self-start rounded-full border border-border bg-surface-2 p-[3px]">
      <button
        type="button"
        aria-label="Светлая тема"
        aria-pressed={theme === "light"}
        onClick={() => setTheme("light")}
        className={cn(
          "flex size-[27px] items-center justify-center rounded-full text-text-3",
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
          "flex size-[27px] items-center justify-center rounded-full text-text-3",
          theme === "dark" && "bg-surface text-accent shadow-sm",
        )}
      >
        <Moon className="size-3.5" />
      </button>
    </div>
  );
}
