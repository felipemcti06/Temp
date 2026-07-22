import { useCallback, useEffect, useState } from 'react'
import ChatWindow from './components/ChatWindow'
import BrandLogo from './components/BrandLogo'
import LoginScreen from './components/LoginScreen'
import ModelSelector, { getSavedModelId, saveModelId } from './components/ModelSelector'
import { apiFetch, apiUrl, clearAuthToken, getAuthToken, setAuthToken } from './api'
import './App.css'

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

export default function App() {
  const [authState, setAuthState] = useState('loading')
  const [username, setUsername] = useState('')
  const [messages, setMessages] = useState([])
  const [sessionId, setSessionId] = useState(null)
  const [loading, setLoading] = useState(false)
  const [mode, setMode] = useState('fallback')
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
    const checkAuth = async () => {
      try {
        const token = getAuthToken()
        const headers = token ? { Authorization: `Bearer ${token}` } : {}
        const res = await fetch(apiUrl('/api/auth/status'), { headers })
        const data = await res.json()

        if (!data.auth_required) {
          setAuthState('authenticated')
          await loadAppData()
          return
        }

        if (data.authenticated) {
          setUsername(data.username || '')
          setAuthState('authenticated')
          await loadAppData()
          return
        }

        clearAuthToken()
        setAuthState('login')
      } catch {
        setAuthState('login')
      }
    }

    checkAuth()
  }, [loadAppData])

  const handleLogin = async (token) => {
    setAuthToken(token)
    setAuthState('authenticated')
    try {
      const res = await fetch(apiUrl('/api/auth/status'), {
        headers: { Authorization: `Bearer ${token}` },
      })
      const data = await res.json()
      setUsername(data.username || '')
      await loadAppData()
    } catch {
      clearAuthToken()
      setAuthState('login')
    }
  }

  const handleLogout = () => {
    clearAuthToken()
    setUsername('')
    setMessages([])
    setSessionId(null)
    setAuthState('login')
  }

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

      try {
        const res = await apiFetch('/api/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            message: text,
            session_id: sessionId,
            model_id: modelId || undefined,
          }),
        })

        if (!res.ok) {
          const err = await res.json().catch(() => ({}))
          throw new Error(err.detail || 'Falha na comunicação com o servidor')
        }

        const data = await res.json()
        setSessionId(data.session_id)
        setMode(data.mode)

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
      }
    },
    [sessionId, modelId],
  )

  if (authState === 'loading') {
    return (
      <div className="login">
        <div className="login__card">
          <p>Carregando...</p>
        </div>
      </div>
    )
  }

  if (authState === 'login') {
    return <LoginScreen onLogin={handleLogin} />
  }

  const modeLabel = MODE_LABELS[mode] || mode

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
            Online · {modeLabel}
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

      <ChatWindow messages={messages} onSend={sendMessage} loading={loading} />

      <footer className="app-footer">
        ChatBot v1.2 · OpenAI + Claude + TM1
      </footer>
    </div>
  )
}
