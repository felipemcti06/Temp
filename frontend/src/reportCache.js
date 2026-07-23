const REPORT_CACHE_KEY = 'chatbot-report-cache-v1'
const REPORT_CACHE_TTL_MS = 180_000

export function normalizePrompt(text) {
  return text.toLowerCase().replace(/\s+/g, ' ').trim()
}

function readStore() {
  try {
    const raw = localStorage.getItem(REPORT_CACHE_KEY)
    return raw ? JSON.parse(raw) : {}
  } catch {
    return {}
  }
}

function writeStore(store) {
  localStorage.setItem(REPORT_CACHE_KEY, JSON.stringify(store))
}

export function getReportCache(prompt) {
  const key = normalizePrompt(prompt)
  const store = readStore()
  const entry = store[key]
  if (!entry) return null
  if (Date.now() - entry.ts > REPORT_CACHE_TTL_MS) {
    delete store[key]
    writeStore(store)
    return null
  }
  return entry.data
}

export function setReportCache(prompt, data) {
  const key = normalizePrompt(prompt)
  const store = readStore()
  store[key] = { ts: Date.now(), data }
  writeStore(store)
}

export function isCacheHitResponse(data) {
  return Boolean(
    data?.cache_hit ||
      data?.response?.includes('Cache TM1') ||
      data?.response?.includes('⚡'),
  )
}
