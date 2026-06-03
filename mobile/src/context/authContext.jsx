import { createContext, useContext, useState, useEffect } from 'react'
import AsyncStorage from '@react-native-async-storage/async-storage'
import client, { silentRequest } from '../api/client'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    AsyncStorage.getItem('token').then(async (token) => {
      if (token) {
        try {
          const { data } = await silentRequest({ method: 'get', url: '/api/auth/me' })
          setUser(data)
        } catch {
          await AsyncStorage.removeItem('token')
        }
      }
    }).finally(() => setLoading(false))
  }, [])

  const login = async (username, password) => {
    const { data } = await client.post('/api/auth/login', { username, password })
    await AsyncStorage.setItem('token', data.access_token)
    try {
      const { data: me } = await client.get('/api/auth/me')
      setUser(me)
    } catch {
      setUser({ username: data.username, role: data.role })
    }
    return data
  }

  const register = async (username, password, email) => {
    await client.post('/api/auth/register', {
      username,
      password,
      email: email || undefined,
      role: 'user',
    })
    return login(username, password)
  }

  const logout = async () => {
    await AsyncStorage.removeItem('token')
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)
