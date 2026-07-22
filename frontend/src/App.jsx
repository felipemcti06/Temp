import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import LoginScreen from './components/LoginScreen'
import ChatApp from './pages/ChatApp'
import ReportPage from './pages/ReportPage'
import { AuthProvider, useAuth } from './hooks/useAuth'
import './App.css'

function ProtectedChat() {
  const { authState, handleLogin } = useAuth()

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

  return <ChatApp />
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<ProtectedChat />} />
          <Route path="/relatorio/:id" element={<ReportPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
