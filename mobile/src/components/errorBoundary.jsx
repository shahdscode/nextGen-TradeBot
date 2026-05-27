import { Component } from 'react'
import { View, Text, ScrollView, StyleSheet } from 'react-native'
import { COLORS } from '../constants/theme'

export default class ErrorBoundary extends Component {
  state = { error: null }

  static getDerivedStateFromError(error) {
    return { error }
  }

  render() {
    if (this.state.error) {
      return (
        <View style={styles.root}>
          <Text style={styles.title}>App failed to load</Text>
          <ScrollView style={styles.scroll}>
            <Text style={styles.message}>{String(this.state.error?.message || this.state.error)}</Text>
          </ScrollView>
        </View>
      )
    }
    return this.props.children
  }
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: COLORS.bg, padding: 24, paddingTop: 60 },
  title: { fontSize: 18, fontWeight: '700', color: COLORS.red, marginBottom: 12 },
  scroll: { flex: 1 },
  message: { fontSize: 13, color: COLORS.textSecondary, fontFamily: 'monospace' },
})
