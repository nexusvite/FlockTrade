import React, { createContext, useState, useEffect, useCallback } from "react";
import {
  login as apiLogin,
  logout as apiLogout,
  fetchMe,
  type User,
} from "../lib/auth";
import { wsClient } from "../lib/websocket";
import { getAccountType, setAccountType as persistAccountType } from "../lib/api";

interface AuthState {
  user: User | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  accountType: "DEMO" | "REAL";
  setAccountType: (t: "DEMO" | "REAL") => void;
}

export const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [accountType, setAccountTypeState] = useState<"DEMO" | "REAL">(getAccountType());

  const setAccountType = useCallback((t: "DEMO" | "REAL") => {
    persistAccountType(t);
    setAccountTypeState(t);
  }, []);

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (token) {
      fetchMe()
        .then(setUser)
        .catch(() => {
          localStorage.removeItem("access_token");
          localStorage.removeItem("refresh_token");
        })
        .finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (user) {
      wsClient.connect();
      return () => wsClient.disconnect();
    }
  }, [user]);

  const login = useCallback(async (username: string, password: string) => {
    const u = await apiLogin(username, password);
    setUser(u);
  }, []);

  const logout = useCallback(async () => {
    await apiLogout();
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, accountType, setAccountType }}>
      {children}
    </AuthContext.Provider>
  );
}
