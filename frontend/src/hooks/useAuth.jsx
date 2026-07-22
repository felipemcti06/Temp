import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { apiUrl, clearAuthToken, getAuthToken, setAuthToken } from '../api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [authState, setAuthState] = useState('loading')
  const [username, setUsername] = useState('')

  const checkAuth = useCallback(async () => {
    try {
      const token = getAuthToken()
      const headers = token ? { Authorization: `Bearer ${token}` } : {}
      const res = await fetch(apiUrl('/api/auth/status'), { headers })
      const data = await res.json()

      if (!data.auth_required) {
        setAuthState('authenticated')
        setUsername(data.username || '')
        return true
      }

      if (data.authenticated) {
        setUsername(data.username || '')
        setAuthState('authenticated')
        return true
      }

      clearAuthToken()
      setUsername('')
      setAuthState('login')
      return false
    } catch {
      setAuthState('login')
      return false
    }
  }, [])

  useEffect(() => {
    checkAuth()
  }, [checkAuth])

  const handleLogin = useCallback(async (token) => {
    setAuthToken(token)
    try {
      const res = await fetch(apiUrl('/api/auth/status'), {
        headers: { Authorization: `Bearer ${token}` },
      })
      const data = await res.json()
      setUsername(data.username || '')
      setAuthState('authenticated')
    } catch {
      clearAuthToken()
      setAuthState('login')
    }
  }, [])

  const handleLogout = useCallback(() => {
    clearAuthToken()
    setUsername('')
    setAuthState('login')
  }, [])

  const value = useMemo(
    () => ({
      authState,
      username,
      checkAuth,
      handleLogin,
      handleLogout,
      isAuthenticated: authState === 'authenticated',
    }),
    [authState, username, checkAuth, handleLogin, handleLogout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth deve ser usado dentro de AuthProvider')
  }
  return context
}
