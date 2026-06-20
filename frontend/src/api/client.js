import axios from 'axios'
import toast from 'react-hot-toast'

// Dev: Vite proxies /api → backend (empty baseURL).
// Prod (Vercel): set VITE_API_URL to your public backend, e.g. https://api.example.com
export function getApiBase() {
  const configured = import.meta.env.VITE_API_URL?.replace(/\/$/, '')
  if (configured) return configured
  return import.meta.env.DEV ? '' : 'http://127.0.0.1:8002'
}

const apiBase = getApiBase()

const client = axios.create({
  baseURL: apiBase,
  timeout: 60000,
})

// Attach stored token on every request
client.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token && !config.headers['Authorization']) {
    config.headers['Authorization'] = `Bearer ${token}`
  }
  return config
})

client.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('token')
      delete client.defaults.headers.common['Authorization']
      if (!window.location.pathname.includes('/login')) {
        window.location.href = '/login'
      }
    } else {
      const msg = err.response?.data?.detail || err.message || 'Something went wrong'
      toast.error(msg)
    }
    return Promise.reject(err)
  }
)

export default client
