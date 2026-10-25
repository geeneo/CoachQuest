import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api } from "./api.js";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(undefined); // undefined = still checking

  const refresh = useCallback(async () => {
    try {
      setUser(await api("/api/auth/me"));
    } catch {
      setUser(null);
    }
  }, []);

  useEffect(() => {
    refresh();
    const onUnauthorized = () => setUser(null);
    window.addEventListener("cq:unauthorized", onUnauthorized);
    return () => window.removeEventListener("cq:unauthorized", onUnauthorized);
  }, [refresh]);

  const login = async (email, password) => setUser(await api("/api/auth/login", { method: "POST", body: { email, password } }));
  const register = async (body) => setUser(await api("/api/auth/register", { method: "POST", body }));
  const logout = async () => {
    await api("/api/auth/logout", { method: "POST" }).catch(() => {});
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, setUser, refresh, login, register, logout }}>{children}</AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
