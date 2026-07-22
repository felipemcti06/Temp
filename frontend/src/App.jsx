import { useCallback, useEffect, useState } from 'react'
import ChatWindow from './components/ChatWindow'
import ModelSelector, { getSavedModelId, saveModelId } from './components/ModelSelector'
import { apiUrl } from './api'
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
  const [messages, setMessages] = useState([])
  const [sessionId, setSessionId] = useState(null)
  const [loading, setLoading] = useState(false)
  const [mode, setMode] = useState('fallback')
  const [models, setModels] = useState([])
  const [modelId, setModelId] = useState('')

  useEffect(() => {
    Promise.all([
      fetch(apiUrl('/api/health')).then((r) => r.json()),
      fetch(apiUrl('/api/models')).then((r) => r.json()),
    ])
      .then(([health, modelsData]) => {
        setMode(health.mode)
        setModels(modelsData.models || [])
        const saved = getSavedModelId()
        const available = (modelsData.models || []).filter((m) => m.available)
        const savedOk = available.some((m) => m.id === saved)
        const initial = savedOk ? saved : modelsData.default || available[0]?.id || ''
        setModelId(initial)
      })
      .catch(() => {})
  }, [])

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
        const res = await fetch(apiUrl('/api/chat'), {
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

  const modeLabel = MODE_LABELS[mode] || mode

  return (
    <div className="app">
      <header className="app-header">
        <div className="app-header__avatar">🤖</div>
        <div className="app-header__info">
          <h1>ChatBot</h1>
          <p>
            <span className="status-dot" />
            Online · {modeLabel}
          </p>
        </div>
      </header>

      <ModelSelector
        models={models}
        value={modelId}
        onChange={handleModelChange}
        disabled={loading}
      />

      <ChatWindow messages={messages} onSend={sendMessage} loading={loading} />

      <footer className="app-footer">
        ChatBot v1.1 · OpenAI + Claude + TM1
      </footer>
    </div>
  )
}
