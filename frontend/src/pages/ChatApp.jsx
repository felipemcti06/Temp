import { useCallback, useEffect, useState } from 'react'
import ChatWindow from '../components/ChatWindow'
import BrandLogo from '../components/BrandLogo'
import ModelSelector, { getSavedModelId, saveModelId } from '../components/ModelSelector'
import { apiFetch, streamChat } from '../api'
import { useAuth } from '../hooks/useAuth'
import '../App.css'

const MODE_LABELS = {
  'openai+tm1': 'GPT + TM1',
  'anthropic+tm1': 'Claude + TM1',
  openai: 'GPT',
  anthropic: 'Claude',
  'ai+tm1': 'IA + TM1',
  ai: 'IA ativada',
  fallback: 'Modo demonstração',
  error: 'Erro de configuração',
}

function formatModeLabel(mode) {
  if (MODE_LABELS[mode]) return MODE_LABELS[mode]
  if (mode.startsWith('agents(')) return 'Agentes (dados → relatório)'
  if (mode === 'fast-path') return 'Fast path (TM1 + template)'
  if (mode === 'fast-path-by-product') return 'Fast path por produto'
  if (mode.includes('+fallback')) return 'IA (fallback)'
  return mode
}

export default function ChatApp() {
  const { username, handleLogout } = useAuth()
  const [messages, setMessages] = useState([])
  const [sessionId, setSessionId] = useState(null)
  const [loading, setLoading] = useState(false)
  const [statusMessage, setStatusMessage] = useState('')
  const [mode, setMode] = useState('fallback')
  const [cacheHit, setCacheHit] = useState(false)
  const [models, setModels] = useState([])
  const [modelId, setModelId] = useState('')

  const loadAppData = useCallback(async () => {
    const [healthRes, modelsRes] = await Promise.all([
      apiFetch('/api/health'),
      apiFetch('/api/models'),
    ])

    const health = await healthRes.json()
    const modelsData = await modelsRes.json()

    setMode(health.mode)
    setModels(modelsData.models || [])

    const saved = getSavedModelId()
    const legacyMap = {
      'anthropic/claude-sonnet-4-20250514': 'anthropic/claude-sonnet-4-6',
      'anthropic/claude-3-5-haiku-20241022': 'anthropic/claude-haiku-4-5',
    }
    const normalizedSaved = legacyMap[saved] || saved
    const available = (modelsData.models || []).filter((m) => m.available)
    const savedOk = available.some((m) => m.id === normalizedSaved)
    const initial = savedOk ? normalizedSaved : modelsData.default || available[0]?.id || ''
    if (normalizedSaved !== saved && normalizedSaved) saveModelId(normalizedSaved)
    setModelId(initial)
  }, [])

  useEffect(() => {
    loadAppData().catch(() => {})
  }, [loadAppData])

  const handleModelChange = (nextId) => {
    setModelId(nextId)
    saveModelId(nextId)
  }

  const sendMessage = useCallback(
    async (text) => {
      const userMsg = {
        role: 'user',
        content: text,
        timestamp: new Date().toISOString(),
      }
      setMessages((prev) => [...prev, userMsg])
      setLoading(true)
      setStatusMessage('Analisando pedido...')
      setCacheHit(false)

      try {
        const data = await streamChat(
          {
            message: text,
            session_id: sessionId,
            model_id: modelId || undefined,
          },
          {
            onStatus: (message) => setStatusMessage(message),
          },
        )

        setSessionId(data.session_id)
        setMode(data.mode)
        setCacheHit(Boolean(data.cache_hit))

        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: data.response,
            timestamp: data.timestamp,
          },
        ])
      } catch (err) {
        if (err.status === 401) {
          handleLogout()
          return
        }
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: err.message || 'Desculpe, ocorreu um erro. Tente novamente em instantes.',
            timestamp: new Date().toISOString(),
          },
        ])
      } finally {
        setLoading(false)
        setStatusMessage('')
      }
    },
    [sessionId, modelId, handleLogout],
  )

  const modeLabel = formatModeLabel(mode)
  const cacheLabel = cacheHit ? ' · Cache TM1' : ''

  return (
    <div className="app">
      <header className="app-header">
        <div className="app-header__avatar">
          <BrandLogo className="brand-logo--header" />
        </div>
        <div className="app-header__info">
          <h1>ChatBot</h1>
          <p>
            <span className="status-dot" />
            Online · {modeLabel}{cacheLabel}
            {username ? ` · ${username}` : ''}
          </p>
        </div>
        <button type="button" className="logout-btn" onClick={handleLogout}>
          Sair
        </button>
      </header>

      <ModelSelector
        models={models}
        value={modelId}
        onChange={handleModelChange}
        disabled={loading}
      />

      <ChatWindow
        messages={messages}
        onSend={sendMessage}
        loading={loading}
        statusMessage={statusMessage}
      />

      <footer className="app-footer">
        ChatBot v1.6 · SSE keep-alive + Cache TM1 visível
      </footer>
    </div>
  )
}
