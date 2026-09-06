import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { checkBackendHealth, checkPiHealth } from "../api/sessions.js";
import { getSession, saveSession as persistSession } from "../api/mockRuns.js";

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

  const loadSession = useCallback((sessionId) => {
    const session = getSession(sessionId);
    setCurrentSession(session);
    return session;
  }, []);

  const startSession = useCallback((session) => {
    persistSession(session);
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
