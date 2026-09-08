import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { checkBackendHealth, checkPiHealth, getSession as fetchSession } from "../api/sessions.js";

const SessionContext = createContext(null);

export function SessionProvider({ children }) {
  const [backendOnline, setBackendOnline] = useState(false);
  const [piOnline, setPiOnline] = useState(false);
  const [currentSession, setCurrentSession] = useState(null);

  // Poll backend (and, once real, Pi) connection status for the Login page's
  // connection-list box. 5s is arbitrary — fine for an operator-facing dot,
  // not meant to be a tight health-check loop.
  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      const [backend, pi] = await Promise.all([checkBackendHealth(), checkPiHealth()]);
      if (!cancelled) {
        setBackendOnline(backend);
        setPiOnline(pi);
      }
    };
    poll();
    const id = setInterval(poll, 5000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  // Rehydrate currentSession from the backend by numeric id (GET /sessions/:id).
  // Used on a hard refresh of /sessions/:id/*, where currentSession starts null.
  const loadSession = useCallback(async (sessionId) => {
    try {
      const session = await fetchSession(sessionId);
      setCurrentSession(session);
      return session;
    } catch {
      setCurrentSession(null);
      return null;
    }
  }, []);

  // The session is already persisted server-side by POST /sessions; just hold
  // the freshly-created object in memory for the next screen.
  const startSession = useCallback((session) => {
    setCurrentSession(session);
  }, []);

  return (
    <SessionContext.Provider
      value={{ backendOnline, piOnline, currentSession, loadSession, startSession, setCurrentSession }}
    >
      {children}
    </SessionContext.Provider>
  );
}

export function useSession() {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used within a SessionProvider");
  return ctx;
}
