import { View, Text, TouchableOpacity, StyleSheet } from 'react-native'
import { StatusBar } from 'expo-status-bar'
import BrandHeader from '../components/brandHeader'
import { COLORS, RADIUS } from '../constants/theme'

export default function WelcomeScreen({ navigation }) {
  return (
    <View style={styles.root}>
      <StatusBar style="light" />
      <View style={styles.inner}>
        <BrandHeader
          size="large"
          subtitle="AI-Powered Trading Intelligence"
        />

        <View style={styles.actions}>
          <TouchableOpacity
            style={styles.primaryBtn}
            onPress={() => navigation.navigate('SignIn')}
            activeOpacity={0.85}
          >
            <Text style={styles.primaryBtnText}>Sign in</Text>
          </TouchableOpacity>

          <TouchableOpacity
            style={styles.secondaryBtn}
            onPress={() => navigation.navigate('SignUp')}
            activeOpacity={0.85}
          >
            <Text style={styles.secondaryBtnText}>Create account</Text>
          </TouchableOpacity>
        </View>
      </View>
    </View>
  )
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: COLORS.bg },
  inner: {
    flex: 1,
    justifyContent: 'center',
    paddingHorizontal: 28,
    paddingBottom: 48,
  },
  actions: { marginTop: 48, gap: 12 },
  primaryBtn: {
    backgroundColor: COLORS.teal,
    borderRadius: RADIUS.md,
    paddingVertical: 16,
    alignItems: 'center',
  },
  primaryBtnText: { color: '#fff', fontSize: 16, fontWeight: '700' },
  secondaryBtn: {
    borderWidth: 1,
    borderColor: COLORS.cardBorder,
    borderRadius: RADIUS.md,
    paddingVertical: 16,
    alignItems: 'center',
    backgroundColor: COLORS.card,
  },
  secondaryBtnText: { color: COLORS.textPrimary, fontSize: 16, fontWeight: '600' },
})
