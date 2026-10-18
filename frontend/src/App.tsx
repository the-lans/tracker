import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient } from "@/lib/queryClient";
import { AuthProvider } from "@/stores/authStore";
import { ThemeProvider } from "@/stores/themeStore";
import { Toaster } from "@/components/ui/toaster";
import { AppShell } from "@/components/layout/AppShell";
import { ProtectedRoute, AdminRoute } from "@/components/layout/ProtectedRoute";
import { LoginPage } from "@/pages/LoginPage";
import { DashboardPage } from "@/pages/DashboardPage";
import { TaskPage } from "@/pages/TaskPage";
import { PipelinesPage } from "@/pages/PipelinesPage";
import { PipelineDetailPage } from "@/pages/PipelineDetailPage";
import { LibraryPage } from "@/pages/LibraryPage";
import { TemplatesPage } from "@/pages/TemplatesPage";
import { RepositoriesPage } from "@/pages/RepositoriesPage";
import { LlmAccountsPage } from "@/pages/LlmAccountsPage";
import { EnvVariablesPage } from "@/pages/EnvVariablesPage";
import { ProfilePage } from "@/pages/ProfilePage";
import { AdminPage } from "@/pages/AdminPage";

export function App() {
  return (
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <BrowserRouter>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route element={<ProtectedRoute />}>
                <Route element={<AppShell />}>
                  <Route index element={<DashboardPage />} />
                  <Route path="tasks/:taskId" element={<TaskPage />} />
                  <Route path="pipelines" element={<PipelinesPage />} />
                  <Route path="pipelines/:pipelineId" element={<PipelineDetailPage />} />
                  <Route path="library" element={<LibraryPage />} />
                  <Route path="templates" element={<TemplatesPage />} />
                  <Route path="repositories" element={<RepositoriesPage />} />
                  <Route path="llm-accounts" element={<LlmAccountsPage />} />
                  <Route path="env-variables" element={<EnvVariablesPage />} />
                  <Route path="profile" element={<ProfilePage />} />
                  <Route element={<AdminRoute />}>
                    <Route path="admin" element={<AdminPage />} />
                  </Route>
                  <Route path="*" element={<Navigate to="/" replace />} />
                </Route>
              </Route>
            </Routes>
          </BrowserRouter>
          <Toaster />
        </AuthProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
