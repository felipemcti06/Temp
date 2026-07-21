export default function MessageBubble({ message }) {
  const isUser = message.role === 'user'
  const time = new Date(message.timestamp).toLocaleTimeString('pt-BR', {
    hour: '2-digit',
    minute: '2-digit',
  })

  return (
    <div className={`message message--${isUser ? 'user' : 'bot'}`}>
      <div className="message__avatar">{isUser ? '👤' : '🤖'}</div>
      <div>
        <div className="message__bubble">{message.content}</div>
        <div className="message__time">{time}</div>
      </div>
    </div>
  )
}
