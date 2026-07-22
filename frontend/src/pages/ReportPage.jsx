import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { apiFetch } from '../api'
import LoginScreen from '../components/LoginScreen'
import { useAuth } from '../hooks/useAuth'
import '../App.css'

export default function ReportPage() {
  const { id } = useParams()
  const { authState, handleLogin } = useAuth()
  const [report, setReport] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (authState !== 'authenticated' || !id) return

    const loadReport = async () => {
      setLoading(true)
      setError('')
      try {
        const res = await apiFetch(`/api/reports/${id}`)
        if (!res.ok) {
          const data = await res.json().catch(() => ({}))
          throw new Error(data.detail || 'Relatório não encontrado')
        }
        setReport(await res.json())
      } catch (err) {
        setError(err.message || 'Não foi possível carregar o relatório')
      } finally {
        setLoading(false)
      }
    }

    loadReport()
  }, [authState, id])

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

  return (
    <div className="report-page">
      <header className="report-page__header">
        <Link to="/" className="report-page__back">
          ← Voltar ao chat
        </Link>
        <h1>{report?.title || 'Relatório'}</h1>
      </header>

      {loading && <p className="report-page__status">Carregando relatório...</p>}
      {error && <p className="report-page__error">{error}</p>}

      {report && !loading && (
        <iframe
          className="report-page__frame"
          title={report.title}
          srcDoc={report.html}
          sandbox="allow-scripts allow-same-origin"
        />
      )}
    </div>
  )
}
