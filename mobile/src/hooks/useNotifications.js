import { useState, useEffect, useRef } from 'react'
import { Platform } from 'react-native'

let Notifications = null
let Device = null
let Constants = null

try {
  Notifications = require('expo-notifications')
  Device = require('expo-device')
} catch {
  // expo-notifications not available in this environment
}

try {
  Constants = require('expo-constants').default
} catch {
  Constants = null
}

export default function useNotifications() {
  const [expoPushToken, setExpoPushToken] = useState(null)
  const notificationListener = useRef(null)

  useEffect(() => {
    if (!Notifications || !Device) return
    // Remote push was removed from Expo Go in SDK 53+ — skip to avoid red error screens
    if (Constants?.appOwnership === 'expo') return

    registerForPushNotificationsAsync()
      .then((token) => {
        if (token) setExpoPushToken(token)
      })
      .catch(() => {
        // Push tokens require EAS projectId in production; ignore in local dev
      })

    Notifications.setNotificationHandler({
      handleNotification: async () => ({
        shouldShowAlert: true,
        shouldPlaySound: true,
        shouldSetBadge: false,
      }),
    })

    const subscription = Notifications.addNotificationReceivedListener(() => {})
    notificationListener.current = subscription
    return () => {
      subscription.remove()
    }
  }, [])

  return { expoPushToken }
}

async function registerForPushNotificationsAsync() {
  if (!Notifications || !Device) return null

  if (Platform.OS === 'android') {
    await Notifications.setNotificationChannelAsync('default', {
      name: 'default',
      importance: Notifications.AndroidImportance.MAX,
      vibrationPattern: [0, 250, 250, 250],
      lightColor: '#14B8A6',
    })
  }

  if (!Device.isDevice) {
    return null  // Push notifications require a physical device
  }

  const { status: existingStatus } = await Notifications.getPermissionsAsync()
  let finalStatus = existingStatus
  if (existingStatus !== 'granted') {
    const { status } = await Notifications.requestPermissionsAsync()
    finalStatus = status
  }
  if (finalStatus !== 'granted') return null

  try {
    // Expo SDK 51+: pass projectId for standalone EAS builds.
    // Falls back gracefully to no-arg call (works in Expo Go).
    const projectId =
      Constants?.expoConfig?.extra?.eas?.projectId ??
      Constants?.easConfig?.projectId ??
      undefined
    const tokenData = await Notifications.getExpoPushTokenAsync(
      projectId ? { projectId } : undefined
    )
    return tokenData.data
  } catch {
    // projectId not configured yet — push tokens unavailable until EAS build is set up
    return null
  }
}
