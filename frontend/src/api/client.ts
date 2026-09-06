const API_BASE_URL = import.meta.env.VITE_API_BASE_URL as string

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

/** Fires whenever a request comes back 401 — the one place session expiry is handled. */
type UnauthorizedHandler = () => void
let onUnauthorized: UnauthorizedHandler | null = null
export function setUnauthorizedHandler(handler: UnauthorizedHandler) {
  onUnauthorized = handler
}

let getToken: () => string | null = () => null
export function setTokenGetter(fn: () => string | null) {
  getToken = fn
}

export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> | undefined),
  }
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }

  const res = await fetch(`${API_BASE_URL}${path}`, { ...options, headers })

  if (res.status === 401) {
    onUnauthorized?.()
    const body = await res.json().catch(() => null)
    throw new ApiError(401, body?.error?.message ?? 'Session expired.')
  }

  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new ApiError(res.status, body?.error?.message ?? `Request failed (${res.status}).`)
  }

  if (res.status === 204) {
    return undefined as T
  }
  return res.json() as Promise<T>
}
