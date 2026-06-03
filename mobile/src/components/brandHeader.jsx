import { View, Text, Image, StyleSheet } from 'react-native'
import { COLORS } from '../constants/theme'

const logo = require('../../assets/icon.png')

export default function BrandHeader({ size = 'large', subtitle }) {
  const isLarge = size === 'large'
  return (
    <View style={styles.wrap}>
      <Image
        source={logo}
        style={[styles.logo, isLarge ? styles.logoLarge : styles.logoSmall]}
        resizeMode="contain"
      />
      <Text style={[styles.name, isLarge ? styles.nameLarge : styles.nameSmall]}>
        nextGen-TradeBot
      </Text>
      {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
    </View>
  )
}

const styles = StyleSheet.create({
  wrap: { alignItems: 'center' },
  logo: { marginBottom: 16 },
  logoLarge: { width: 120, height: 120, borderRadius: 28 },
  logoSmall: { width: 72, height: 72, borderRadius: 18 },
  name: { color: COLORS.textPrimary, fontWeight: '800', letterSpacing: 0.3 },
  nameLarge: { fontSize: 26 },
  nameSmall: { fontSize: 20 },
  subtitle: {
    marginTop: 8,
    fontSize: 13,
    color: COLORS.textMuted,
    textAlign: 'center',
  },
})
