import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { apiFetch, setTokenGetter, setUnauthorizedHandler } from '../api/client'
import type { LoginRequest, RegisterRequest, RegisterResponse, TokenResponse } from '../api/types'

const STORAGE_KEY = 'ngai_token'

interface AuthContextValue {
  token: string | null
  sessionMessage: string | null
  login: (payload: LoginRequest) => Promise<void>
  register: (payload: RegisterRequest) => Promise<RegisterResponse>
  logout: () => void
  clearSessionMessage: () => void
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

  useEffect(() => {
    setTokenGetter(() => token)
  }, [token])

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

  const value = useMemo(
    () => ({ token, sessionMessage, login, register, logout: () => logout(null), clearSessionMessage }),
    [token, sessionMessage, login, register, logout, clearSessionMessage],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
