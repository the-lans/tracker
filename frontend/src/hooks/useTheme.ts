import { useContext } from "react";
import { ThemeContext, type ThemeContextValue } from "@/stores/themeContext";

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (ctx === null) {
    throw new Error("useTheme должен использоваться внутри ThemeProvider");
  }
  return ctx;
}
