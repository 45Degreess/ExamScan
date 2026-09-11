import { BrowserRouter, Navigate, Routes, Route } from "react-router-dom";
import { SessionProvider } from "./context/SessionContext.jsx";
import { AuthProvider } from "./context/AuthContext.jsx";
import ProtectedRoute from "./components/ProtectedRoute.jsx";
import AppShell from "./components/AppShell.jsx";
import LoginPage from "./pages/LoginPage.jsx";
import DashboardPage from "./pages/DashboardPage.jsx";
import AdminUsersPage from "./pages/AdminUsersPage.jsx";
import CreateSessionPage from "./pages/CreateSessionPage.jsx";
import PrepareSessionPage from "./pages/PrepareSessionPage.jsx";
import ReviewSessionPage from "./pages/ReviewSessionPage.jsx";
import ViewSessionPage from "./pages/ViewSessionPage.jsx";
import DebugPage from "./pages/DebugPage.jsx";

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<ProtectedRoute />}>
            <Route element={<SessionProvider><AppShell /></SessionProvider>}>
              <Route path="/" element={<DashboardPage />} />
              <Route path="/home" element={<Navigate to="/" replace />} />
              <Route path="/sessions/new" element={<CreateSessionPage />} />
              <Route path="/sessions/:sessionId/prepare" element={<PrepareSessionPage />} />
              <Route path="/sessions/:sessionId/review" element={<ReviewSessionPage />} />
              <Route path="/sessions/:sessionId" element={<ViewSessionPage />} />
              <Route path="/debug" element={<DebugPage />} />
              <Route element={<ProtectedRoute adminOnly />}>
                <Route path="/admin/users" element={<AdminUsersPage />} />
              </Route>
            </Route>
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
