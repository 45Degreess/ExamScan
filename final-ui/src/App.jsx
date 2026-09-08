import { BrowserRouter, Routes, Route } from "react-router-dom";
import { SessionProvider } from "./context/SessionContext.jsx";
import LoginPage from "./pages/LoginPage.jsx";
import CreateSessionPage from "./pages/CreateSessionPage.jsx";
import PrepareSessionPage from "./pages/PrepareSessionPage.jsx";
import ReviewSessionPage from "./pages/ReviewSessionPage.jsx";
import ViewSessionPage from "./pages/ViewSessionPage.jsx";
import DebugPage from "./pages/DebugPage.jsx";

export default function App() {
  return (
    <SessionProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<LoginPage />} />
          <Route path="/sessions/new" element={<CreateSessionPage />} />
          <Route path="/sessions/:sessionId/prepare" element={<PrepareSessionPage />} />
          <Route path="/sessions/:sessionId/review" element={<ReviewSessionPage />} />
          <Route path="/sessions/:sessionId" element={<ViewSessionPage />} />
          <Route path="/debug" element={<DebugPage />} />
        </Routes>
      </BrowserRouter>
    </SessionProvider>
  );
}
