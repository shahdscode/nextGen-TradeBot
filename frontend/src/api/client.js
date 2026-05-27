import axios from 'axios'
import toast from 'react-hot-toast'

const client = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://127.0.0.1:8002',
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
