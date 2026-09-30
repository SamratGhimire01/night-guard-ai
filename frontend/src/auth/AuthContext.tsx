import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { apiFetch, setTokenGetter, setUnauthorizedHandler } from '../api/client'
import type { LoginRequest, RegisterRequest, RegisterResponse, TokenResponse } from '../api/types'

const STORAGE_KEY = 'ngai_token'

/** UI-only convenience (which buttons to show) — never a security boundary.
 * The role also travels in the JWT the backend already validates on every
 * request, so a tampered/decoded-wrong value here can only ever change what
 * renders, never what a `require_role(["owner","admin"])` route will accept. */
function decodeRole(token: string): string | null {
  try {
    const payload = JSON.parse(atob(token.split('.')[1]))
    return typeof payload.role === 'string' ? payload.role : null
  } catch {
    return null
  }
}

interface AuthContextValue {
  token: string | null
  role: string | null
  sessionMessage: string | null
  login: (payload: LoginRequest) => Promise<void>
  register: (payload: RegisterRequest) => Promise<RegisterResponse>
  logout: () => void
  clearSessionMessage: () => void
  /** Starts a session from a token the API already issued (password reset, invite, password change). */
  startSession: (token: string) => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  // sessionStorage (not localStorage): the JWT doesn't outlive the tab/browser
  // session or sync across tabs, which shrinks the exposure window if this app
  // were ever hit by XSS. A true httpOnly cookie would be stronger still, but
  // that needs the backend to issue/read auth cookies — Phase 3's login is
  // bearer-token-only, and changing that is out of scope for this shell phase.
  const [token, setToken] = useState<string | null>(() => sessionStorage.getItem(STORAGE_KEY))
  const [sessionMessage, setSessionMessage] = useState<string | null>(null)

  // Set synchronously during render, NOT in a useEffect: React runs effects
  // child-first, parent-last on mount, so a child several levels down (e.g.
  // DashboardLayout, which fires its own apiFetch calls in ITS OWN mount
  // effect) would otherwise run before this effect ever set the real token —
  // apiFetch would see the module's default no-op getter, send an
  // unauthenticated request, get a real 401, and the global 401 handler would
  // log a genuinely-still-valid session out with a false "session expired"
  // message. This was a real, reproducible bug: any hard reload or direct
  // navigation into a dashboard route (not just a client-side <Link> click)
  // hit it every time. Calling this directly in the render body (a plain
  // module-level variable assignment, not a React state update) means the
  // getter is always correct before ANY child even starts rendering.
  setTokenGetter(() => token)

  const logout = useCallback((message: string | null = null) => {
    sessionStorage.removeItem(STORAGE_KEY)
    setToken(null)
    setSessionMessage(message)
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(() => logout('Your session expired. Please log in again.'))
  }, [logout])

  const login = useCallback(async (payload: LoginRequest) => {
    const res = await apiFetch<TokenResponse>('/auth/login', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
    sessionStorage.setItem(STORAGE_KEY, res.access_token)
    setToken(res.access_token)
    setSessionMessage(null)
  }, [])

  const register = useCallback(async (payload: RegisterRequest) => {
    return apiFetch<RegisterResponse>('/auth/register', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  }, [])

  const clearSessionMessage = useCallback(() => setSessionMessage(null), [])

  const startSession = useCallback((next: string) => {
    sessionStorage.setItem(STORAGE_KEY, next)
    setToken(next)
    setSessionMessage(null)
  }, [])

  const role = useMemo(() => (token ? decodeRole(token) : null), [token])

  const value = useMemo(
    () => ({ token, role, sessionMessage, login, register, logout: () => logout(null), clearSessionMessage, startSession }),
    [token, role, sessionMessage, login, register, logout, clearSessionMessage, startSession],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
