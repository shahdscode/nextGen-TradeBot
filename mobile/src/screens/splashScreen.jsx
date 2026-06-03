import { useEffect } from 'react'
import { View, StyleSheet } from 'react-native'
import { StatusBar } from 'expo-status-bar'
import BrandHeader from '../components/brandHeader'
import { COLORS } from '../constants/theme'

export default function SplashScreen({ navigation }) {
  useEffect(() => {
    const timer = setTimeout(() => {
      navigation.replace('Welcome')
    }, 2500)
    return () => clearTimeout(timer)
  }, [navigation])

  return (
    <View style={styles.root}>
      <StatusBar style="light" />
      <BrandHeader
        size="large"
        subtitle="AI-Powered Trading Intelligence"
      />
    </View>
  )
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: COLORS.bg,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 32,
  },
})
