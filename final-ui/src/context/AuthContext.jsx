import { createContext, useCallback, useContext, useEffect, useState } from "react";
import * as authApi from "../api/auth.js";
import { setCsrfToken } from "../api/client.js";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const clearAuthentication = useCallback(() => {
    setCsrfToken("");
    setUser(null);
  }, []);

  const refresh = useCallback(async () => {
    try {
      const result = await authApi.getCurrentUser();
      setCsrfToken(result.csrf_token);
      setUser(result.user);
      return result.user;
    } catch {
      clearAuthentication();
      return null;
    } finally {
      setLoading(false);
    }
  }, [clearAuthentication]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    const handleUnauthorized = () => clearAuthentication();
    window.addEventListener("examscan:unauthorized", handleUnauthorized);
    return () => window.removeEventListener("examscan:unauthorized", handleUnauthorized);
  }, [clearAuthentication]);

  const signIn = useCallback(async (uctId, password) => {
    const result = await authApi.login(uctId, password);
    setCsrfToken(result.csrf_token);
    setUser(result.user);
    return result.user;
  }, []);

  const signOut = useCallback(async () => {
    try {
      await authApi.logout();
    } finally {
      clearAuthentication();
    }
  }, [clearAuthentication]);

  return (
    <AuthContext.Provider
      value={{ user, loading, signIn, signOut, requestPassword: authApi.requestPassword, refresh }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within an AuthProvider");
  return context;
}
