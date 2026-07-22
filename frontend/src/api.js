const API_BASE = import.meta.env.VITE_API_URL || ''
const TOKEN_KEY = 'chatbot-auth-token'

export function apiUrl(path) {
  return `${API_BASE}${path}`
}

export function getAuthToken() {
  return localStorage.getItem(TOKEN_KEY)
}

export function setAuthToken(token) {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearAuthToken() {
  localStorage.removeItem(TOKEN_KEY)
}

export function authHeaders(extra = {}) {
  const headers = { ...extra }
  const token = getAuthToken()
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }
  return headers
}

export async function apiFetch(path, options = {}) {
  const res = await fetch(apiUrl(path), {
    ...options,
    headers: authHeaders(options.headers || {}),
  })

  if (res.status === 401) {
    clearAuthToken()
    const err = new Error('Sessão expirada')
    err.status = 401
    throw err
  }

  return res
}
