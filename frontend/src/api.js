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

function parseSseBlock(block) {
  const lines = block.split('\n')
  let event = 'message'
  const dataLines = []

  for (const line of lines) {
    if (line.startsWith('event:')) {
      event = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trim())
    }
  }

  if (!dataLines.length) return null
  return { event, data: JSON.parse(dataLines.join('\n')) }
}

export async function streamChat(payload, { onStatus, onDone, onError }) {
  const res = await apiFetch('/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Falha na comunicação com o servidor')
  }

  if (!res.body) {
    throw new Error('Streaming não suportado neste navegador')
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const parts = buffer.split('\n\n')
    buffer = parts.pop() || ''

    for (const part of parts) {
      const parsed = parseSseBlock(part.trim())
      if (!parsed) continue

      if (parsed.event === 'status') {
        onStatus?.(parsed.data.message)
      } else if (parsed.event === 'ping') {
        // keep-alive — mantém conexão SSE viva durante consultas longas
      } else if (parsed.event === 'done') {
        onDone?.(parsed.data)
        return parsed.data
      } else if (parsed.event === 'error') {
        const err = new Error(parsed.data.detail || 'Erro ao gerar resposta')
        onError?.(err)
        throw err
      }
    }
  }

  throw new Error('Conexão encerrada antes da resposta final')
}
