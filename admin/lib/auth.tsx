import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { api, setOnUnauthorized } from './api';

const STORAGE_KEY = 'heracles_admin_token';
const EMAIL_KEY = 'heracles_admin_email';

function load(key: string): string | null {
  if (typeof window === 'undefined' || !window.localStorage) return null;
  return window.localStorage.getItem(key);
}
function save(key: string, value: string | null): void {
  if (typeof window === 'undefined' || !window.localStorage) return;
  if (value === null) window.localStorage.removeItem(key);
  else window.localStorage.setItem(key, value);
}

interface AuthState {
  token: string | null;
  email: string | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [email, setEmail] = useState<string | null>(null);

  useEffect(() => {
    setToken(load(STORAGE_KEY));
    setEmail(load(EMAIL_KEY));
  }, []);

  const logout = useCallback(() => {
    setToken(null);
    setEmail(null);
    save(STORAGE_KEY, null);
    save(EMAIL_KEY, null);
  }, []);

  useEffect(() => {
    setOnUnauthorized(() => logout());
  }, [logout]);

  const login = useCallback(async (e: string, password: string) => {
    const res = await api.login(e, password);
    setToken(res.token);
    setEmail(res.admin.email);
    save(STORAGE_KEY, res.token);
    save(EMAIL_KEY, res.admin.email);
  }, []);

  const value = useMemo(
    () => ({ token, email, login, logout }),
    [token, email, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
