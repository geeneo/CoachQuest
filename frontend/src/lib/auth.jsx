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

  // After signing in, check that the browser kept the session cookie. It drops
  // a Secure cookie on plain http, which otherwise looks like "nothing happens".
  const confirmSession = async (signedIn) => {
    try {
      setUser(await api("/api/auth/me"));
    } catch {
      throw new Error(
        window.location.protocol === "http:"
          ? `Signed in as ${signedIn.email}, but the browser refused the session cookie because this page is on http://. ` +
              "Open the site over https://, or set COOKIE_SECURE=false in .env for testing and restart the api container."
          : `Signed in as ${signedIn.email}, but the browser did not keep the session cookie. ` +
              "Check that cookies are allowed for this site and that the proxy passes Set-Cookie headers.",
      );
    }
  };
  const login = async (email, password) =>
    confirmSession(await api("/api/auth/login", { method: "POST", body: { email, password } }));
  const register = async (body) => confirmSession(await api("/api/auth/register", { method: "POST", body }));
  const logout = async () => {
    await api("/api/auth/logout", { method: "POST" }).catch(() => {});
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, setUser, refresh, login, register, logout }}>{children}</AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
