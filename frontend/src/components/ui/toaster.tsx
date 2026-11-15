import { Toaster as SonnerToaster } from "sonner";
import { useTheme } from "@/hooks/useTheme";

export function Toaster() {
  const { theme } = useTheme();
  return (
    <SonnerToaster
      theme={theme}
      position="bottom-right"
      offset={{ bottom: 128, right: 16 }}
      mobileOffset={{ bottom: 128, right: 16, left: 16 }}
      toastOptions={{
        style: {
          background: "var(--surface)",
          color: "var(--text)",
          border: "1px solid var(--border)",
        },
      }}
    />
  );
}
