import { useEffect, useRef } from 'react'
import MessageBubble from './MessageBubble'
import ChatInput from './ChatInput'
import BrandLogo from './BrandLogo'

const SUGGESTIONS = [
  'Olá! Como você funciona?',
  'Me conte uma curiosidade',
  'Preciso de ajuda',
]

export default function ChatWindow({ messages, onSend, loading }) {
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  return (
    <div className="chat-container">
      <div className="messages">
        {messages.length === 0 && (
          <div className="welcome">
            <div className="welcome__icon">
              <BrandLogo className="brand-logo--welcome" />
            </div>
            <h2>Bem-vindo ao ChatBot!</h2>
            <p>
              Sou seu assistente virtual. Pode me perguntar qualquer coisa ou
              simplesmente bater um papo.
            </p>
            <div className="suggestions">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  className="suggestion"
                  onClick={() => onSend(s)}
                  disabled={loading}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <MessageBubble key={i} message={msg} />
        ))}

        {loading && (
          <div className="message message--bot">
            <div className="message__avatar">
              <BrandLogo className="brand-logo--message" />
            </div>
            <div className="typing">
              <span />
              <span />
              <span />
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      <ChatInput onSend={onSend} disabled={loading} />
    </div>
  )
}
