const { loadNgrokToken } = require('./ngrokEnv')

const API_PORT = 8002

/**
 * Public URL for the FastAPI backend.
 * @param {{ reserveNgrokForExpo?: boolean }} opts
 *   When true (remote mode), use localtunnel for API so ngrok free tier
 *   stays available for `expo start --tunnel`.
 */
async function startApiTunnel(opts = {}) {
  const { reserveNgrokForExpo = false } = opts
  const token = loadNgrokToken()

  if (!reserveNgrokForExpo && token) {
    try {
      const ngrok = require('@ngrok/ngrok')
      const listener = await ngrok.forward({ addr: API_PORT, authtoken: token })
      const url = listener.url()
      if (url) {
        return {
          url,
          kind: 'ngrok',
          close: async () => listener.close(),
        }
      }
    } catch {
      /* try v4 */
    }

    try {
      const ngrok = require('ngrok')
      const url = await ngrok.connect({ addr: API_PORT, authtoken: token, proto: 'http' })
      if (url) {
        return {
          url,
          kind: 'ngrok',
          close: async () => {
            await ngrok.disconnect()
            await ngrok.kill()
          },
        }
      }
    } catch {
      /* fall through */
    }
  }

  const lt = require('localtunnel')
  const tunnel = await lt({ port: API_PORT })
  return {
    url: tunnel.url,
    kind: 'localtunnel',
    close: () =>
      new Promise((resolve) => {
        tunnel.close()
        resolve()
      }),
  }
}

module.exports = { startApiTunnel, API_PORT }
