const { getDefaultConfig } = require('expo/metro-config')

const config = getDefaultConfig(__dirname)

config.server = {
  ...config.server,
  host: '0.0.0.0',
}

// Smaller dev bundles over Expo tunnel (avoids timeouts on slow networks).
config.transformer = {
  ...config.transformer,
  unstable_allowRequireContext: true,
}

module.exports = config
