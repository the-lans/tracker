import { useContext } from "react";
import { AuthContext, type AuthContextValue } from "@/stores/authContext";

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (ctx === null) {
    throw new Error("useAuth должен использоваться внутри AuthProvider");
  }
  return ctx;
}
