import { useCallback, useEffect, useState } from 'react'
import ChatWindow from './components/ChatWindow'
import { apiUrl } from './api'
import './App.css'

export default function App() {
  const [messages, setMessages] = useState([])
  const [sessionId, setSessionId] = useState(null)
  const [loading, setLoading] = useState(false)
  const [mode, setMode] = useState('fallback')

  useEffect(() => {
    fetch(apiUrl('/api/health'))
      .then((r) => r.json())
      .then((data) => setMode(data.mode))
      .catch(() => {})
  }, [])

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
          body: JSON.stringify({ message: text, session_id: sessionId }),
        })

        if (!res.ok) throw new Error('Falha na comunicação com o servidor')

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
      } catch {
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: 'Desculpe, ocorreu um erro. Tente novamente em instantes.',
            timestamp: new Date().toISOString(),
          },
        ])
      } finally {
        setLoading(false)
      }
    },
    [sessionId],
  )

  const modeLabel = mode === 'ai' ? 'IA ativada' : 'Modo demonstração'

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

      <ChatWindow messages={messages} onSend={sendMessage} loading={loading} />

      <footer className="app-footer">
        ChatBot v1.0 · Feito com React + FastAPI
      </footer>
    </div>
  )
}
