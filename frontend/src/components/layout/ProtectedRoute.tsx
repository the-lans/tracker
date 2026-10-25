import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import { UserRole } from "@/lib/types";

export function ProtectedRoute() {
  const { isAuthenticated } = useAuth();
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  return <Outlet />;
}

/** Раздел 19.2: разделы администрирования доступны только роли `admin` — и
 * на фронте, и (обязательный дубль) на бэкенде через `Depends(require_admin)`. */
export function AdminRoute() {
  const { user } = useAuth();
  if (user?.role !== UserRole.ADMIN) return <Navigate to="/" replace />;
  return <Outlet />;
}
