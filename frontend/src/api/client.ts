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
  const isFormData = options.body instanceof FormData
  const headers: Record<string, string> = {
    // FormData (file upload) must NOT set Content-Type manually — the browser
    // needs to add its own multipart boundary, which we can't know in advance.
    ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
    // Real, documented ngrok behavior (found live testing the mobile check-in
    // scanner, Phase 46): ngrok's free tier shows an HTML "you're about to
    // visit..." interstitial for ANY request with a real browser User-Agent,
    // including a cross-origin fetch() — not just a top-level page
    // navigation — which silently breaks every API call when the API itself
    // is tunneled. This header is ngrok's own documented bypass; harmless
    // and ignored by every other host (production, plain localhost), so
    // it's safe to always send rather than only during ngrok testing.
    'ngrok-skip-browser-warning': 'true',
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

/** Downloads a real file response (e.g. a report's .xlsx) — apiFetch always
 * does res.json(), which would corrupt binary content, so this is a small,
 * separate fetch that reuses the same auth/401 handling and saves the real
 * bytes via a throwaway <a> + object URL (revoked immediately after). */
export async function downloadFile(path: string, filename: string): Promise<void> {
  const token = getToken()
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })

  if (res.status === 401) {
    onUnauthorized?.()
    throw new ApiError(401, 'Session expired.')
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new ApiError(res.status, body?.error?.message ?? `Download failed (${res.status}).`)
  }

  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}
