import { Link } from 'react-router-dom'
import BrandLogo from './BrandLogo'

const REPORT_LINK_RE = /\/relatorio\/[0-9a-f-]{36}/gi

function extractReportLinks(content) {
  const matches = content.match(REPORT_LINK_RE) || []
  return [...new Set(matches)]
}

export default function MessageBubble({ message }) {
  const isUser = message.role === 'user'
  const time = new Date(message.timestamp).toLocaleTimeString('pt-BR', {
    hour: '2-digit',
    minute: '2-digit',
  })

  const reportLinks = !isUser ? extractReportLinks(message.content) : []

  return (
    <div className={`message message--${isUser ? 'user' : 'bot'}`}>
      <div className="message__avatar">
        {isUser ? '👤' : <BrandLogo className="brand-logo--message" />}
      </div>
      <div>
        <div className="message__bubble">{message.content}</div>
        {reportLinks.length > 0 && (
          <div className="message__actions">
            {reportLinks.map((path) => (
              <Link key={path} to={path} className="report-link report-link--button">
                Abrir relatório
              </Link>
            ))}
          </div>
        )}
        <div className="message__time">{time}</div>
      </div>
    </div>
  )
}
